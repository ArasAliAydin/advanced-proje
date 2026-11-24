"""Kişisel istatistikler ve doluluk tahmini (yalnızca okuma yapar, hiçbir veriyi değiştirmez).

Doluluk tahmini — ağırlıklı hareketli ortalama
    Hedef günün her saati için, aynı haftanın gününün son `FORECAST_WEEKS` haftasındaki doluluğa
    bakılır. Yakın haftalar daha ağırlıklı sayılır (4 hafta için ağırlıklar 4, 3, 2, 1):

        tahmin(saat) = Σ ağırlık_k · doluluk(gün − 7k, saat) / Σ ağırlık_k

    Doluluk = o saatte rezerve edilmiş koltuk-saat / odanın o saatteki kapasitesi (0..1).
    "Rezerve edilmiş" iptal dışındaki tüm durumlardır: gelinmeyen (no_show) rezervasyon da
    o koltuğu başkasına kapattığı için talebe sayılır.
    Resmi tatil olan ve henüz bitmemiş (bugün ve sonrası) geçmiş günler hesaba katılmaz.
    O gün için şimdiden yapılmış rezervasyonlar da bilinir: beklenen doluluk = max(tahmin, şu anki doluluk).
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import Holiday, Reservation, ReservationStatus, Room, User
from app.services import scheduling
from app.services.reservation_service import COUNTED_FOR_LIMITS, BookingError, seats_limit


FORECAST_WEEKS = 4
HISTORY_WEEKS = 8

LEVELS = (
    (0.35, "low"),
    (0.70, "medium"),
    (float("inf"), "high"),
)

ATTENDED = (
    ReservationStatus.checked_in,
    ReservationStatus.completed,
)

WEEKDAYS = [
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
]


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def _rate(part: float, whole: float) -> float | None:
    return round(part / whole, 3) if whole else None


# ---------------------------------------------------------------
# KİŞİSEL İSTATİSTİKLER
# ---------------------------------------------------------------

def my_stats(session: Session, user: User, now: datetime) -> dict:

    reservations = list(
        session.exec(
            select(Reservation).where(
                Reservation.user_id == user.id
            )
        ).all()
    )

    by_status = Counter(r.status for r in reservations)

    attended = [
        r for r in reservations
        if r.status in ATTENDED
    ]

    no_show = by_status[ReservationStatus.no_show]

    def used(lo: datetime, hi: datetime) -> float:
        """Günlük ve haftalık limite sayılan rezervasyon saatleri."""

        return round(
            sum(
                _hours(r.start_time, r.end_time)
                for r in reservations
                if (
                    r.status in COUNTED_FOR_LIMITS
                    and r.start_time < hi
                    and r.end_time > lo
                )
            ),
            2,
        )

    week_lo, week_hi = scheduling.week_bounds(now.date())
    day_lo, day_hi = scheduling.day_bounds(now.date())

    week_used = used(week_lo, week_hi)
    day_used = used(day_lo, day_hi)

    # En çok kullanılan oda

    room_hours: dict[int, float] = defaultdict(float)

    for r in attended:
        room_hours[r.room_id] += _hours(
            r.start_time,
            r.end_time,
        )

    favorite_room = None

    if room_hours:

        room_id = max(
            room_hours,
            key=lambda rid: (
                room_hours[rid],
                -rid,
            ),
        )

        room = session.get(Room, room_id)

        favorite_room = {
            "room_id": room_id,
            "room_name": room.name if room else None,
            "hours": round(room_hours[room_id], 2),
        }

    # En çok tercih edilen saat ve gün

    hour_counts = Counter(
        r.start_time.hour for r in attended
    )

    weekday_counts = Counter(
        r.start_time.weekday() for r in attended
    )

    favorite_hour = (
        min(
            hour_counts,
            key=lambda h: (-hour_counts[h], h),
        )
        if hour_counts
        else None
    )

    favorite_weekday = (
        min(
            weekday_counts,
            key=lambda d: (-weekday_counts[d], d),
        )
        if weekday_counts
        else None
    )

    # Haftalık kullanım geçmişi

    history = []

    for k in range(HISTORY_WEEKS - 1, -1, -1):

        lo = week_lo - timedelta(weeks=k)
        hi = lo + timedelta(weeks=1)

        history.append({
            "week_start": lo.date(),
            "booked_hours": used(lo, hi),
            "attended_hours": round(
                sum(
                    _hours(r.start_time, r.end_time)
                    for r in attended
                    if lo <= r.start_time < hi
                ),
                2,
            ),
        })

    # Üst üste katılım sağlanan hafta sayısı

    attended_weeks = {
        scheduling.week_bounds(r.start_time.date())[0]
        for r in attended
    }

    cursor = (
        week_lo
        if week_lo in attended_weeks
        else week_lo - timedelta(weeks=1)
    )

    streak = 0

    while cursor in attended_weeks:
        streak += 1
        cursor -= timedelta(weeks=1)

    # Yaklaşan rezervasyonlar

    upcoming = [
        r for r in reservations
        if (
            r.status in (
                ReservationStatus.confirmed,
                ReservationStatus.checked_in,
            )
            and r.end_time > now
        )
    ]

    return {
        "week_start": week_lo.date(),
        "week_used_hours": week_used,
        "week_limit_hours": settings.WEEKLY_LIMIT_HOURS,
        "week_remaining_hours": round(
            max(
                0.0,
                settings.WEEKLY_LIMIT_HOURS - week_used,
            ),
            2,
        ),
        "day_used_hours": day_used,
        "day_limit_hours": settings.DAILY_LIMIT_HOURS,
        "total_reservations": len(reservations),
        "attended": len(attended),
        "attended_hours": round(
            sum(
                _hours(r.start_time, r.end_time)
                for r in attended
            ),
            2,
        ),
        "no_show": no_show,
        "cancelled": by_status[ReservationStatus.cancelled],
        "upcoming": len(upcoming),
        "attendance_rate": _rate(
            len(attended),
            len(attended) + no_show,
        ),
        "no_show_rate": _rate(
            no_show,
            len(attended) + no_show,
        ),
        "favorite_room": favorite_room,
        "favorite_hour": favorite_hour,
        "favorite_weekday": favorite_weekday,
        "favorite_weekday_name": (
            WEEKDAYS[favorite_weekday]
            if favorite_weekday is not None
            else None
        ),
        "streak_weeks": streak,
        "penalty_points": user.penalty_points,
        "penalty_threshold": settings.PENALTY_BAN_THRESHOLD,
        "banned_until": (
            user.banned_until
            if user.banned_until and user.banned_until > now
            else None
        ),
        "weekly_history": history,
    }


# ---------------------------------------------------------------
# DOLULUK TAHMİNİ
# ---------------------------------------------------------------

def _open_fraction(room: Room, hour: int) -> float:
    """Odanın ilgili saatte açık olduğu süre oranı."""

    open_m = (
        room.open_time.hour * 60
        + room.open_time.minute
    )

    close_m = (
        room.close_time.hour * 60
        + room.close_time.minute
    )

    return max(
        0,
        min(close_m, hour * 60 + 60)
        - max(open_m, hour * 60),
    ) / 60


def _level(rate: float) -> str:

    return next(
        name
        for limit, name in LEVELS
        if rate < limit
    )


def _hourly_occupancy(
    reservations: list[Reservation],
    room: Room,
    day: date,
) -> dict[int, float]:

    booked: dict[int, float] = defaultdict(float)

    for r in reservations:

        for bucket_day, hour, hours in scheduling.hour_buckets(
            r.start_time,
            r.end_time,
        ):

            if bucket_day == day:
                booked[hour] += hours

    seats = seats_limit(room)

    result = {}

    for hour in range(24):

        capacity = _open_fraction(room, hour) * seats

        if capacity:
            result[hour] = min(
                1.0,
                booked[hour] / capacity,
            )

    return result


def forecast(
    session: Session,
    room: Room,
    day: date,
    now: datetime,
    weeks: int = FORECAST_WEEKS,
) -> dict:

    # -----------------------------------------------------------
    # DÜZELTİLEN BÖLÜM
    # -----------------------------------------------------------

    if not (
        now.date()
        <= day
        <= now.date() + timedelta(days=settings.MAX_ADVANCE_DAYS)
    ):

        raise BookingError(
            "forecast_range",
            f"Tahmin bugünden itibaren en fazla {settings.MAX_ADVANCE_DAYS} gün için yapılabilir",
            400,
            {"days": settings.MAX_ADVANCE_DAYS},
        )

    # -----------------------------------------------------------
    # GEÇMİŞ HAFTALARIN HESAPLANMASI
    # -----------------------------------------------------------

    candidates = [
        (k, day - timedelta(weeks=k))
        for k in range(1, weeks + 1)
    ]

    holidays = set(
        session.exec(
            select(Holiday.day).where(
                col(Holiday.day).in_(
                    [d for _, d in candidates]
                )
            )
        ).all()
    )

    history = [
        (weeks + 1 - k, d)
        for k, d in candidates
        if d < now.date() and d not in holidays
    ]

    days = [d for _, d in history] + [day]

    lo = datetime.combine(
        min(days),
        datetime.min.time(),
    )

    hi = (
        datetime.combine(
            max(days),
            datetime.min.time(),
        )
        + timedelta(days=1)
    )

    rows = list(
        session.exec(
            select(Reservation).where(
                Reservation.room_id == room.id,
                Reservation.status != ReservationStatus.cancelled,
                Reservation.start_time < hi,
                Reservation.end_time > lo,
            )
        ).all()
    )

    by_day: dict[date, list[Reservation]] = defaultdict(list)

    for r in rows:
        by_day[r.start_time.date()].append(r)

    past = {
        d: _hourly_occupancy(by_day[d], room, d)
        for _, d in history
    }

    current = _hourly_occupancy(
        by_day[day],
        room,
        day,
    )

    total_weight = sum(
        w for w, _ in history
    )

    hours = []

    for hour, booked_now in current.items():

        predicted = (
            round(
                sum(
                    w * past[d].get(hour, 0.0)
                    for w, d in history
                ) / total_weight,
                3,
            )
            if total_weight
            else None
        )

        expected = round(
            max(predicted or 0.0, booked_now),
            3,
        )

        hours.append({
            "hour": hour,
            "predicted": predicted,
            "booked_now": round(booked_now, 3),
            "expected": expected,
            "level": _level(expected),
            "past": (
                datetime.combine(
                    day,
                    datetime.min.time(),
                )
                + timedelta(hours=hour + 1)
                <= now
            ),
        })

    future = [
        h for h in hours
        if not h["past"]
    ]

    best = sorted(
        future,
        key=lambda h: (
            h["expected"],
            h["hour"],
        ),
    )[:3]

    peak = max(
        hours,
        key=lambda h: (
            h["expected"],
            -h["hour"],
        ),
        default=None,
    )

    return {
        "room_id": room.id,
        "day": day,
        "weekday": day.weekday(),
        "weeks_used": len(history),
        "history_days": sorted(
            d for _, d in history
        ),
        "hours": hours,
        "best_hours": [
            h["hour"] for h in best
        ],
        "peak_hour": (
            peak["hour"]
            if peak and peak["expected"] > 0
            else None
        ),
    }