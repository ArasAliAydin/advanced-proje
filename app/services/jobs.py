"""Zamanlanmış arka plan görevleri. Her fonksiyon `now` alır, böylece testte zaman kontrol edilir."""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.core import clock
from app.core.config import settings
from app.core.database import engine
from app.models import Reservation, ReservationStatus, Room, User, WaitlistEntry, WaitlistStatus
from app.services import reservation_service as rs
from app.services.notifications import notify
from app.services.penalties import add_penalty
from app.services.waitlist_service import promote_waitlist

logger = logging.getLogger("studyspot.jobs")


def process_no_shows(session: Session, now: datetime) -> int:
    """Check-in süresi dolan rezervasyonları no_show yapar, ceza verir, slotu bekleyenlere açar."""
    stmt = select(Reservation).where(
        Reservation.status == ReservationStatus.confirmed, Reservation.start_time < now
    )
    count = 0
    for reservation in session.exec(stmt).all():
        if now <= rs.checkin_deadline(reservation):
            continue
        reservation.status = ReservationStatus.no_show
        session.add(reservation)
        user = session.get(User, reservation.user_id)
        room = session.get(Room, reservation.room_id)
        body = (
            f"{room.name} - {reservation.start_time:%d.%m.%Y %H:%M} rezervasyonunuza check-in yapılmadığı için "
            "iptal edildi"
        )
        if rs.penalty_exempt(reservation):
            body += ". Bekleme listesinden son anda atandığınız için ceza puanı uygulanmadı."
        else:
            add_penalty(
                session, user, settings.NO_SHOW_PENALTY_POINTS, "Rezervasyona gelmeme (no-show)", now, reservation.id
            )
            body += f" ve {settings.NO_SHOW_PENALTY_POINTS} ceza puanı eklendi."
        notify(session, user, "StudySpot: Rezervasyonunuz iptal edildi (gelmediniz)", body, "no_show")
        session.flush()
        promote_waitlist(session, room, reservation.start_time, reservation.end_time, now)
        count += 1
    return count


def complete_finished(session: Session, now: datetime) -> int:
    stmt = select(Reservation).where(
        Reservation.status == ReservationStatus.checked_in, Reservation.end_time <= now
    )
    rows = session.exec(stmt).all()
    for reservation in rows:
        reservation.status = ReservationStatus.completed
        session.add(reservation)
    return len(rows)


def send_reminders(session: Session, now: datetime) -> int:
    stmt = select(Reservation).where(
        Reservation.status == ReservationStatus.confirmed,
        Reservation.reminder_sent == False,  # noqa: E712
        Reservation.start_time > now,
        Reservation.start_time <= now + timedelta(minutes=settings.REMINDER_MINUTES_BEFORE),
    )
    rows = session.exec(stmt).all()
    for reservation in rows:
        room = session.get(Room, reservation.room_id)
        notify(
            session,
            session.get(User, reservation.user_id),
            "StudySpot: Rezervasyon hatırlatması",
            f"{room.name} ({room.location}) rezervasyonunuz {reservation.start_time:%H:%M}'de başlıyor. "
            "QR kodunuzla check-in yapmayı unutmayın.",
            "reminder",
        )
        reservation.reminder_sent = True
        session.add(reservation)
    return len(rows)


def expire_waitlist(session: Session, now: datetime) -> int:
    stmt = select(WaitlistEntry).where(
        WaitlistEntry.status == WaitlistStatus.waiting, WaitlistEntry.end_time <= now
    )
    rows = session.exec(stmt).all()
    for entry in rows:
        entry.status = WaitlistStatus.expired
        session.add(entry)
    return len(rows)


def run_all(session: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or clock.now()
    with rs.booking_lock:
        result = {
            "no_shows": process_no_shows(session, now),
            "completed": complete_finished(session, now),
            "reminders": send_reminders(session, now),
            "waitlist_expired": expire_waitlist(session, now),
        }
        session.commit()
    return result


def _run_once() -> None:
    with Session(engine) as session:
        result = run_all(session)
    if any(result.values()):
        logger.info("Zamanlanmış görevler: %s", result)


async def scheduler_loop() -> None:
    """Uygulama ömrü boyunca görevleri periyodik çalıştırır (main.py lifespan başlatır)."""
    while True:
        try:
            await asyncio.to_thread(_run_once)
        except Exception:
            logger.exception("Zamanlanmış görev hatası")
        await asyncio.sleep(settings.SCHEDULER_INTERVAL_SECONDS)
