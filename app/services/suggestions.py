"""Akıllı slot önerisi: istenen slot doluysa kurallara uyan en iyi alternatifleri sıralar.

Aday üretimi
  1. Aynı oda, aynı gün: odanın slot ızgarasına hizalı, istenenle aynı süredeki tüm başlangıçlar.
  2. Diğer aktif odalar, istenenle aynı saat aralığı.

Eleme
  Her aday, gerçek rezervasyonda kullanılan fonksiyonlardan geçer: `validate_time_rules`
  (çalışma saati, hizalama, geçmiş, 14 gün sınırı ...), kullanıcının o saatte başka
  rezervasyonu (`ensure_no_user_conflict`), günlük/haftalık limit (`ensure_within_limits`)
  ve kalan koltuk (`remaining_seats`, sweep-line). Yani önerilen her slot, o an
  `POST /reservations` ile gerçekten alınabilir.

Skor (her bileşen 0..1, sonuç da 0..1)
  yakınlık  = max(0, 1 - |Δt| / SUGGEST_HORIZON_HOURS)
              Δt: önerinin başlangıcı ile istenen başlangıç arasındaki fark. Diğer odalar
              aynı saatte olduğu için yakınlıkları 1'dir.
  uyum      = ½ · tip uyumu + ½ · kapasite oranı              (aynı oda için 1)
              tip uyumu: aynı room_type 1, yalnızca aynı booking_mode 0.5, değilse 0
              kapasite oranı: min(c₁, c₂) / max(c₁, c₂)
  sakinlik  = 1 - geçmiş doluluk
              Son SUGGEST_HISTORY_DAYS günde, adayın haftanın aynı günü ve aynı saatlerindeki
              doluluk oranı (analytics._matrix ile aynı hesap; aralık birden fazla saate
              yayılıyorsa saatlere düşen süreyle ağırlıklı ortalama).
  skor      = (w_y·yakınlık + w_u·uyum + w_s·sakinlik) / (w_y + w_u + w_s)

Ağırlıklar `.env` ile değiştirilebilir (SUGGEST_WEIGHT_*). Varsayılanlar: zamana yakınlık en
önemli (0.5), çünkü öğrenci büyük olasılıkla o saate göre plan yapmıştır; ardından oda uyumu
(0.3), çünkü 6 kişilik grup için tek kişilik koltuk işe yaramaz; sakinlik (0.2) eşitlik bozucu
gibi çalışır ve kalabalık saatlerden uzaklaştırır.
"""
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.core import clock
from app.core.config import settings
from app.models import Room, RoomType, User
from app.schemas import OccupancyCell, SuggestionRead
from app.services import analytics, holidays, scheduling
from app.services import reservation_service as rs
from app.services.reservation_service import BookingError

ROOM_TYPE_LABELS = {
    RoomType.study_room: "grup çalışma odası",
    RoomType.lab: "laboratuvar",
    RoomType.hall: "salon",
}

Rates = dict[tuple[int, int], float]


@dataclass(frozen=True)
class Weights:
    proximity: float = 0.5
    fit: float = 0.3
    quiet: float = 0.2

    @classmethod
    def from_settings(cls) -> "Weights":
        return cls(settings.SUGGEST_WEIGHT_PROXIMITY, settings.SUGGEST_WEIGHT_FIT, settings.SUGGEST_WEIGHT_QUIET)

    def combine(self, proximity: float, fit: float, quiet: float) -> float:
        total = self.proximity + self.fit + self.quiet
        if total <= 0:
            return 0.0
        return (self.proximity * proximity + self.fit * fit + self.quiet * quiet) / total


# --- Saf skor fonksiyonları (DB'den bağımsız, birim testlenebilir) ---
def proximity_score(delta: timedelta, horizon_hours: float) -> float:
    if horizon_hours <= 0:
        return 1.0 if not delta else 0.0
    return max(0.0, 1 - abs(delta.total_seconds()) / (horizon_hours * 3600))


def fit_score(requested: Room, candidate: Room) -> float:
    if candidate.id == requested.id:
        return 1.0
    if candidate.room_type == requested.room_type:
        type_match = 1.0
    elif candidate.booking_mode == requested.booking_mode:
        type_match = 0.5
    else:
        type_match = 0.0
    capacity_ratio = min(candidate.capacity, requested.capacity) / max(candidate.capacity, requested.capacity)
    return 0.5 * type_match + 0.5 * capacity_ratio


def historical_occupancy(rates: Rates, start: datetime, end: datetime) -> float:
    """Aralığın saatlerine düşen geçmiş doluluk oranlarının süre ağırlıklı ortalaması."""
    weighted = total = 0.0
    for day, hour, hours in scheduling.hour_buckets(start, end):
        weighted += rates.get((day.weekday(), hour), 0.0) * hours
        total += hours
    return weighted / total if total else 0.0


# --- Yardımcılar ---
def history_range(now: datetime) -> tuple[date, date]:
    """Geçmiş doluluk penceresi: dünden geriye SUGGEST_HISTORY_DAYS gün (bugün hariç, henüz bitmedi)."""
    d_to = now.date() - timedelta(days=1)
    return d_to - timedelta(days=max(1, settings.SUGGEST_HISTORY_DAYS) - 1), d_to


def _grid(room: Room, day: date, duration: timedelta) -> Iterator[datetime]:
    """Odanın o günkü slot ızgarasına hizalı, `duration` süresinin sığdığı tüm başlangıçlar."""
    start = datetime.combine(day, room.open_time)
    closing = datetime.combine(day, room.close_time)
    step = timedelta(minutes=room.slot_minutes)
    while start + duration <= closing:
        yield start
        start += step


def _bookable(session: Session, user: User, room: Room, start: datetime, end: datetime, now: datetime) -> int | None:
    """Aday tüm kurallardan geçerse kalan koltuk sayısını, geçmezse None döndürür."""
    try:
        rs.validate_time_rules(room, start, end, now)
        rs.ensure_no_user_conflict(session, user, start, end)
        rs.ensure_within_limits(session, user, start, end)
    except BookingError:
        return None
    remaining = rs.remaining_seats(session, room, start, end)
    return remaining if remaining > 0 else None


def _format_delta(delta: timedelta) -> str:
    minutes = int(abs(delta.total_seconds()) // 60)
    hours, minutes = divmod(minutes, 60)
    parts = ([f"{hours} saat"] if hours else []) + ([f"{minutes} dk"] if minutes else [])
    return " ".join(parts) + (" sonra" if delta > timedelta(0) else " önce")


def _reasons(requested: Room, candidate: Room, delta: timedelta, occupancy: float, remaining: int) -> list[str]:
    if candidate.id == requested.id:
        reasons = [f"Aynı oda, istenen saatten {_format_delta(delta)}"]
    else:
        reasons = ["Aynı saat, farklı oda"]
        if candidate.room_type == requested.room_type:
            reasons.append(f"Aynı tipte oda ({ROOM_TYPE_LABELS[candidate.room_type]})")
        else:
            reasons.append(f"Farklı oda tipi ({ROOM_TYPE_LABELS[candidate.room_type]})")
        reasons.append(f"Kapasite {candidate.capacity} (istenen oda: {requested.capacity})")
    reasons.append(f"Geçmişte bu saatlerde doluluk %{round(occupancy * 100)}")
    if candidate.booking_mode.value == "shared":
        reasons.append(f"Kalan koltuk: {remaining}")
    return reasons


# --- Ana fonksiyonlar ---
def suggest(
    session: Session,
    user: User,
    room_id: int,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
    limit: int | None = None,
    weights: Weights | None = None,
) -> list[SuggestionRead]:
    """İstenen [start, end) yerine alınabilecek slotları skora göre azalan sırada döndürür.

    İstenen slotun kendisi öneriye girmez (boş olsa bile). Kullanıcı cezalı/pasifse
    BookingError fırlatır: o durumda hiçbir öneri alınamaz ve nedeni söylenmelidir.
    """
    now = now or clock.now()
    limit = limit or settings.SUGGEST_LIMIT
    weights = weights or Weights.from_settings()
    requested = rs.get_room(session, room_id)
    if end <= start or start.date() != end.date():
        raise BookingError("invalid_interval", "Bitiş saati başlangıçtan sonra ve aynı gün içinde olmalı")
    rs.ensure_user_eligible(user, now)
    if holidays.holiday_name(session, start.date()):
        return []

    d_from, d_to = history_range(now)
    rates_cache: dict[int, Rates] = {}

    def rates_of(room: Room) -> Rates:
        if room.id not in rates_cache:
            rates_cache[room.id] = analytics.occupancy_rates(session, d_from, d_to, room.id)
        return rates_cache[room.id]

    duration = end - start
    candidates: list[tuple[Room, datetime]] = [
        (requested, s) for s in _grid(requested, start.date(), duration) if s != start
    ]
    others = session.exec(
        select(Room).where(Room.is_active == True, Room.id != requested.id).order_by(Room.name)  # noqa: E712
    ).all()
    candidates += [(room, start) for room in others]

    results: list[SuggestionRead] = []
    for room, s in candidates:
        e = s + duration
        remaining = _bookable(session, user, room, s, e, now)
        if remaining is None:
            continue
        delta = s - start
        proximity = proximity_score(delta, settings.SUGGEST_HORIZON_HOURS)
        fit = fit_score(requested, room)
        occupancy = historical_occupancy(rates_of(room), s, e)
        quiet = 1 - occupancy
        results.append(
            SuggestionRead(
                room_id=room.id,
                room_name=room.name,
                room_type=room.room_type,
                start_time=s,
                end_time=e,
                remaining_seats=remaining,
                same_room=room.id == requested.id,
                score=round(weights.combine(proximity, fit, quiet), 3),
                proximity_score=round(proximity, 3),
                fit_score=round(fit, 3),
                quiet_score=round(quiet, 3),
                historical_occupancy=round(occupancy, 3),
                reasons=_reasons(requested, room, delta, occupancy, remaining),
            )
        )
    # Eşit skorda istenen saate daha yakın olan, sonra aynı oda, sonra isim/saat sırası
    results.sort(
        key=lambda r: (-r.score, abs((r.start_time - start).total_seconds()), not r.same_room, r.room_name, r.start_time)
    )
    return results[:limit]


def quiet_hours(session: Session, room: Room, now: datetime, weekday: int | None = None, limit: int = 5) -> list[OccupancyCell]:
    """Odanın geçmiş veriye göre en sakin saatleri (doluluğu en düşükten yükseğe).

    `weekday` verilirse yalnızca o gün (0 = Pazartesi), verilmezse tüm günlerin ortalaması.
    """
    d_from, d_to = history_range(now)
    if weekday is None:
        cells = analytics.by_hour(session, d_from, d_to, room.id)
    else:
        cells = [c for c in analytics.heatmap(session, d_from, d_to, room.id) if c.weekday == weekday]
    return sorted(cells, key=lambda c: (c.occupancy_rate, c.hour))[:limit]
