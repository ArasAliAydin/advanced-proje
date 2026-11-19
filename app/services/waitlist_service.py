"""Bekleme listesi: FIFO sıra ve slot boşalınca sıradakine otomatik atama."""
from datetime import datetime

from sqlmodel import Session, select

from app.core import clock
from app.models import ReservationSource, Role, Room, User, WaitlistEntry, WaitlistStatus
from app.services import reservation_service as rs
from app.services.notifications import notify
from app.services.reservation_service import BookingError


def _waiting_overlapping(session: Session, room_id: int, start: datetime, end: datetime) -> list[WaitlistEntry]:
    stmt = (
        select(WaitlistEntry)
        .where(
            WaitlistEntry.room_id == room_id,
            WaitlistEntry.status == WaitlistStatus.waiting,
            WaitlistEntry.start_time < end,
            WaitlistEntry.end_time > start,
        )
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)  # FIFO
    )
    return list(session.exec(stmt).all())


def position(session: Session, entry: WaitlistEntry) -> int | None:
    """Aynı slotu bekleyenler arasındaki sıra (1 = ilk)."""
    if entry.status != WaitlistStatus.waiting:
        return None
    queue = _waiting_overlapping(session, entry.room_id, entry.start_time, entry.end_time)
    return [e.id for e in queue].index(entry.id) + 1


def join(session: Session, user: User, room_id: int, start: datetime, end: datetime) -> WaitlistEntry:
    now = clock.now()
    with rs.booking_lock:
        room = rs.get_room(session, room_id)
        rs.validate_time_rules(room, start, end, now)
        rs.ensure_user_eligible(user, now)
        rs.ensure_no_user_conflict(session, user, start, end)
        if any(e.user_id == user.id for e in _waiting_overlapping(session, room_id, start, end)):
            raise BookingError("already_waiting", "Bu saat aralığı için zaten bekleme listesindesiniz", 409)
        if rs.remaining_seats(session, room, start, end) > 0:
            raise BookingError("slot_available", "Bu saat aralığı müsait, doğrudan rezervasyon yapabilirsiniz")
        entry = WaitlistEntry(user_id=user.id, room_id=room_id, start_time=start, end_time=end, created_at=now)
        session.add(entry)
        session.commit()
    session.refresh(entry)
    return entry


def leave(session: Session, entry: WaitlistEntry, actor: User) -> WaitlistEntry:
    if actor.role != Role.admin and actor.id != entry.user_id:
        raise BookingError("forbidden", "Bu kayıt size ait değil", 403)
    if entry.status != WaitlistStatus.waiting:
        raise BookingError("not_waiting", "Bu kayıt artık beklemede değil", 409)
    entry.status = WaitlistStatus.cancelled
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def promote_waitlist(session: Session, room: Room, start: datetime, end: datetime, now: datetime) -> int:
    """Boşalan [start, end) aralığıyla kesişen bekleyenleri sırayla yerleştirmeyi dener.

    Her aday için rezervasyon kurallarının tamamı yeniden doğrulanır (çakışma, limit,
    ceza). Uymayan aday atlanır ve sırada kalır; böylece boşalan 2 saatlik bir slot,
    1'er saat bekleyen iki farklı kişiye de dağıtılabilir. Commit çağırana aittir.
    """
    promoted = 0
    for entry in _waiting_overlapping(session, room.id, start, end):
        if entry.end_time <= now:
            continue
        user = session.get(User, entry.user_id)
        try:
            reservation = rs.create_reservation(
                session,
                user,
                room,
                entry.start_time,
                entry.end_time,
                now,
                source=ReservationSource.waitlist,
                allow_started=True,
            )
        except BookingError:
            continue
        entry.status = WaitlistStatus.promoted
        entry.promoted_reservation_id = reservation.id
        session.add(entry)
        notify(
            session,
            user,
            "StudySpot: Bekleme listesinden rezervasyonunuz oluşturuldu",
            f"{room.name} - {entry.start_time:%d.%m.%Y %H:%M}-{entry.end_time:%H:%M} slotu boşaldı "
            "ve rezervasyon otomatik olarak adınıza yapıldı.",
            "waitlist_promoted",
        )
        promoted += 1
    session.flush()
    return promoted
