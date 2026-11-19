"""Rezervasyon iş kuralları: çakışma tespiti, limitler, iptal, check-in."""
import threading
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from app.core import clock
from app.core.config import settings
from app.models import (
    BookingMode,
    Reservation,
    ReservationSource,
    ReservationStatus,
    Role,
    Room,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from app.services import holidays, scheduling
from app.services.notifications import notify
from app.services.penalties import add_penalty

# Kontrol + kayıt adımları atomik olmalı; aksi halde iki eşzamanlı istek aynı slotu alabilir.
booking_lock = threading.RLock()

# Slotu fiilen işgal eden durumlar
OCCUPYING = (ReservationStatus.confirmed, ReservationStatus.checked_in)
# Günlük/haftalık limite sayılan durumlar (gelmeyenler de hakkını harcamış sayılır)
COUNTED_FOR_LIMITS = (
    ReservationStatus.confirmed,
    ReservationStatus.checked_in,
    ReservationStatus.completed,
    ReservationStatus.no_show,
)


class BookingError(Exception):
    """İş kuralı ihlali. main.py'deki handler bunu JSON hata yanıtına çevirir."""

    def __init__(self, code: str, message: str, status_code: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        # Yanıta eklenecek ek alanlar (ör. slot_full yanıtındaki "suggestions")
        self.extra: dict = extra or {}


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def seats_limit(room: Room) -> int:
    return 1 if room.booking_mode == BookingMode.exclusive else room.capacity


def get_room(session: Session, room_id: int) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise BookingError("room_not_found", "Oda bulunamadı", 404)
    return room


def occupying_reservations(session: Session, room_id: int, start: datetime, end: datetime) -> list[Reservation]:
    stmt = select(Reservation).where(
        Reservation.room_id == room_id,
        col(Reservation.status).in_(OCCUPYING),
        Reservation.start_time < end,
        Reservation.end_time > start,
    )
    return list(session.exec(stmt).all())


def remaining_seats(session: Session, room: Room, start: datetime, end: datetime) -> int:
    busy = [(r.start_time, r.end_time) for r in occupying_reservations(session, room.id, start, end)]
    return seats_limit(room) - scheduling.peak_concurrency(busy, start, end)


def validate_time_rules(room: Room, start: datetime, end: datetime, now: datetime, allow_started: bool = False) -> None:
    if end <= start:
        raise BookingError("invalid_interval", "Bitiş saati başlangıçtan sonra olmalı")
    if start.date() != end.date():
        raise BookingError("invalid_interval", "Rezervasyon tek bir gün içinde olmalı")
    if start.second or start.microsecond or end.second or end.microsecond:
        raise BookingError("invalid_interval", "Saatler dakika hassasiyetinde olmalı")
    if not room.is_active:
        raise BookingError("room_inactive", "Bu oda şu anda rezervasyona kapalı")
    if start.time() < room.open_time or end.time() > room.close_time:
        raise BookingError(
            "outside_hours", f"Oda yalnızca {room.open_time:%H:%M}-{room.close_time:%H:%M} arasında açık"
        )
    opening = datetime.combine(start.date(), room.open_time)
    slot = timedelta(minutes=room.slot_minutes)
    if (start - opening) % slot or (end - start) % slot:
        raise BookingError("slot_misaligned", f"Saatler {room.slot_minutes} dakikalık dilimlere uymalı")
    if _hours(start, end) > settings.MAX_RESERVATION_HOURS:
        raise BookingError("too_long", f"Tek rezervasyon en fazla {settings.MAX_RESERVATION_HOURS:g} saat olabilir")
    # Bekleme listesinden atamada (allow_started) başlamış ama bitmemiş slot da verilebilir
    if (end if allow_started else start) <= now:
        raise BookingError("in_past", "Geçmiş bir zaman için rezervasyon yapılamaz")
    if start.date() > now.date() + timedelta(days=settings.MAX_ADVANCE_DAYS):
        raise BookingError("too_far", f"En fazla {settings.MAX_ADVANCE_DAYS} gün sonrasına rezervasyon yapılabilir")


def ensure_user_eligible(user: User, now: datetime) -> None:
    if not user.is_active:
        raise BookingError("user_inactive", "Hesabınız aktif değil", 403)
    if user.banned_until and user.banned_until > now:
        raise BookingError(
            "user_banned",
            f"Ceza nedeniyle {user.banned_until:%d.%m.%Y %H:%M} tarihine kadar rezervasyon yapamazsınız",
            403,
        )


def _user_reservations(session: Session, user_id: int, start: datetime, end: datetime, statuses) -> list[Reservation]:
    stmt = select(Reservation).where(
        Reservation.user_id == user_id,
        col(Reservation.status).in_(statuses),
        Reservation.start_time < end,
        Reservation.end_time > start,
    )
    return list(session.exec(stmt).all())


def ensure_no_user_conflict(session: Session, user: User, start: datetime, end: datetime) -> None:
    if _user_reservations(session, user.id, start, end, OCCUPYING):
        raise BookingError("user_conflict", "Bu saat aralığında başka bir rezervasyonunuz var", 409)


def ensure_within_limits(session: Session, user: User, start: datetime, end: datetime) -> None:
    """Günlük ve haftalık toplam saat limitleri (yalnızca öğrenciler)."""
    if user.role != Role.student:
        return
    requested = _hours(start, end)
    checks = (
        (scheduling.day_bounds(start.date()), settings.DAILY_LIMIT_HOURS, "daily_limit", "Günlük"),
        (scheduling.week_bounds(start.date()), settings.WEEKLY_LIMIT_HOURS, "weekly_limit", "Haftalık"),
    )
    for (lo, hi), limit, code, label in checks:
        used = sum(
            _hours(r.start_time, r.end_time) for r in _user_reservations(session, user.id, lo, hi, COUNTED_FOR_LIMITS)
        )
        if used + requested > limit:
            raise BookingError(
                code, f"{label} rezervasyon limitiniz {limit:g} saat (kullanılan: {used:g} saat)", 409
            )


def create_reservation(
    session: Session,
    user: User,
    room: Room,
    start: datetime,
    end: datetime,
    now: datetime,
    source: ReservationSource = ReservationSource.direct,
    allow_started: bool = False,
) -> Reservation:
    """Tüm kuralları doğrular ve rezervasyonu oturuma ekler (commit etmez)."""
    validate_time_rules(room, start, end, now, allow_started)
    ensure_user_eligible(user, now)
    ensure_no_user_conflict(session, user, start, end)
    ensure_within_limits(session, user, start, end)
    holiday = holidays.holiday_name(session, start.date())
    if holiday:
        raise BookingError("holiday", f"{start:%d.%m.%Y} resmi tatil ({holiday}), rezervasyon yapılamaz")
    if remaining_seats(session, room, start, end) <= 0:
        raise BookingError("slot_full", "Bu saat aralığı dolu. Bekleme listesine katılabilirsiniz.", 409)
    reservation = Reservation(
        user_id=user.id, room_id=room.id, start_time=start, end_time=end, source=source, created_at=now
    )
    session.add(reservation)
    session.flush()
    return reservation


def book(session: Session, user: User, room_id: int, start: datetime, end: datetime) -> Reservation:
    now = clock.now()
    with booking_lock:
        room = get_room(session, room_id)
        reservation = create_reservation(session, user, room, start, end, now)
        notify(
            session,
            user,
            "StudySpot: Rezervasyonunuz onaylandı",
            f"{room.name} - {start:%d.%m.%Y %H:%M}-{end:%H:%M}. "
            f"Başlangıçtan sonraki {settings.CHECKIN_GRACE_MINUTES} dakika içinde QR ile check-in yapmayı unutmayın.",
            "reservation_confirmed",
        )
        session.commit()
    session.refresh(reservation)
    return reservation


def cancel(session: Session, reservation: Reservation, actor: User, reason: str | None = None) -> Reservation:
    from app.services.waitlist_service import promote_waitlist  # döngüsel import'u kırmak için

    now = clock.now()
    is_admin = actor.role == Role.admin
    with booking_lock:
        session.refresh(reservation)
        if reservation.status != ReservationStatus.confirmed:
            raise BookingError("not_cancellable", "Yalnızca onaylı (confirmed) rezervasyonlar iptal edilebilir", 409)
        if not is_admin and now >= reservation.start_time:
            raise BookingError("already_started", "Başlamış bir rezervasyon iptal edilemez", 409)
        reservation.status = ReservationStatus.cancelled
        reservation.cancelled_at = now
        reservation.cancel_reason = reason or ("Admin tarafından iptal" if is_admin else "Kullanıcı iptali")
        session.add(reservation)
        owner = session.get(User, reservation.user_id)
        room = session.get(Room, reservation.room_id)
        if actor.id == reservation.user_id:
            late = reservation.start_time - now < timedelta(minutes=settings.LATE_CANCEL_MINUTES)
            if late and not is_admin and not penalty_exempt(reservation):
                add_penalty(
                    session, owner, settings.LATE_CANCEL_PENALTY_POINTS, "Geç iptal", now, reservation.id
                )
        else:
            notify(
                session,
                owner,
                "StudySpot: Rezervasyonunuz iptal edildi",
                f"{room.name} - {reservation.start_time:%d.%m.%Y %H:%M} rezervasyonunuz iptal edildi. "
                f"Neden: {reservation.cancel_reason}",
                "reservation_cancelled",
            )
        session.flush()
        promote_waitlist(session, room, reservation.start_time, reservation.end_time, now)
        session.commit()
    session.refresh(reservation)
    return reservation


ROOM_CLOSED_REASON = "Oda rezervasyona kapatıldı"


def close_room(session: Session, room: Room, now: datetime) -> int:
    """Odayı rezervasyona kapatır ve commit eder; iptal edilen rezervasyon sayısını döndürür.

    Henüz başlamamış onaylı rezervasyonlar cezasız iptal edilip sahiplerine bildirilir,
    bekleme listesi kayıtları kapatılır. Başlamış olanlara dokunulmaz.
    """
    with booking_lock:
        room.is_active = False
        session.add(room)
        upcoming = session.exec(
            select(Reservation).where(
                Reservation.room_id == room.id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time > now,
            )
        ).all()
        for reservation in upcoming:
            reservation.status = ReservationStatus.cancelled
            reservation.cancelled_at = now
            reservation.cancel_reason = ROOM_CLOSED_REASON
            session.add(reservation)
            notify(
                session,
                session.get(User, reservation.user_id),
                "StudySpot: Rezervasyonunuz iptal edildi",
                f"{room.name} - {reservation.start_time:%d.%m.%Y %H:%M} rezervasyonunuz iptal edildi. "
                f"Neden: {ROOM_CLOSED_REASON}",
                "reservation_cancelled",
            )
        waiting = session.exec(
            select(WaitlistEntry).where(
                WaitlistEntry.room_id == room.id, WaitlistEntry.status == WaitlistStatus.waiting
            )
        ).all()
        for entry in waiting:
            entry.status = WaitlistStatus.cancelled
            session.add(entry)
        session.commit()
    return len(upcoming)


def penalty_exempt(reservation: Reservation) -> bool:
    """Cezasız iptal süresi kalmadan bekleme listesinden atanan rezervasyon ceza doğurmaz.

    Kullanıcı bu rezervasyonu o anda kendisi onaylamadı ve cezasız iptal etme fırsatı
    hiç olmadı; geç iptal veya no-show için puan yazmak haksızlık olur.
    """
    return (
        reservation.source == ReservationSource.waitlist
        and reservation.created_at >= reservation.start_time - timedelta(minutes=settings.LATE_CANCEL_MINUTES)
    )


def checkin_deadline(reservation: Reservation) -> datetime:
    """Son check-in anı. Bekleme listesinden geç atananlar için süre atama anından başlar,
    ama slotun bitişini aşamaz."""
    deadline = max(reservation.start_time, reservation.created_at) + timedelta(minutes=settings.CHECKIN_GRACE_MINUTES)
    return min(deadline, reservation.end_time)


def check_in(session: Session, code: str, actor: User) -> Reservation:
    now = clock.now()
    reservation = session.exec(select(Reservation).where(Reservation.checkin_code == code)).first()
    if reservation is None:
        raise BookingError("invalid_code", "Geçersiz check-in kodu", 404)
    if actor.role != Role.admin and actor.id != reservation.user_id:
        raise BookingError("forbidden", "Bu rezervasyon size ait değil", 403)
    if reservation.status == ReservationStatus.checked_in:
        raise BookingError("already_checked_in", "Bu rezervasyon için zaten check-in yapılmış", 409)
    if reservation.status != ReservationStatus.confirmed:
        raise BookingError("not_active", f"Rezervasyon durumu check-in'e uygun değil ({reservation.status.value})", 409)
    opens = reservation.start_time - timedelta(minutes=settings.CHECKIN_OPEN_MINUTES_BEFORE)
    if now < opens:
        raise BookingError("too_early", f"Check-in {opens:%H:%M} itibarıyla açılır", 409)
    if now > checkin_deadline(reservation) or now >= reservation.end_time:
        raise BookingError("too_late", "Check-in süresi doldu", 409)
    reservation.status = ReservationStatus.checked_in
    reservation.checked_in_at = now
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation
