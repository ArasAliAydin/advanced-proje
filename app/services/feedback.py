"""Oda puanları ve bakım/arıza bildirimleri."""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core import clock
from app.models import (
    BookingMode,
    MaintenanceIssue,
    Reservation,
    ReservationStatus,
    Room,
    RoomDirectRating,
    RoomRating,
    User,
)


def _eligible_reservation(session: Session, reservation_id: int, user: User) -> Reservation:
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rezervasyon bulunamadı")
    if reservation.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu rezervasyon size ait değil")
    if reservation.status != ReservationStatus.completed or reservation.checked_in_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Yalnızca check-in yapılmış ve tamamlanmış rezervasyonlar kullanılabilir",
        )
    return reservation


def submit_rating(
    session: Session, reservation_id: int, user: User, rating: int, comment: str | None
) -> RoomRating:
    reservation = _eligible_reservation(session, reservation_id, user)
    existing = session.exec(select(RoomRating).where(RoomRating.reservation_id == reservation.id)).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu rezervasyon zaten puanlanmış")
    item = RoomRating(
        reservation_id=reservation.id,
        user_id=user.id,
        room_id=reservation.room_id,
        rating=rating,
        comment=comment.strip() or None if comment else None,
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu rezervasyon zaten puanlanmış")
    session.refresh(item)
    return item


def submit_issue(session: Session, reservation_id: int, user: User, description: str) -> MaintenanceIssue:
    reservation = _eligible_reservation(session, reservation_id, user)
    issue = MaintenanceIssue(
        reservation_id=reservation.id,
        user_id=user.id,
        room_id=reservation.room_id,
        description=description.strip(),
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return issue


def list_my_ratings(session: Session, user: User) -> list[RoomRating]:
    return session.exec(
        select(RoomRating).where(RoomRating.user_id == user.id).order_by(RoomRating.created_at.desc())
    ).all()


def rate_room(
    session: Session, room_id: int, user: User, rating: int, comment: str | None
) -> RoomDirectRating:
    if session.get(Room, room_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Oda bulunamadı")
    item = session.exec(
        select(RoomDirectRating).where(
            RoomDirectRating.room_id == room_id,
            RoomDirectRating.user_id == user.id,
        )
    ).first()
    if item is None:
        item = RoomDirectRating(user_id=user.id, room_id=room_id, rating=rating)
    item.rating = rating
    item.comment = comment.strip() or None if comment else None
    item.updated_at = clock.now()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def list_my_room_ratings(session: Session, user: User) -> list[RoomDirectRating]:
    return session.exec(
        select(RoomDirectRating).where(RoomDirectRating.user_id == user.id).order_by(RoomDirectRating.room_id)
    ).all()


def create_demo_reservation(session: Session, room_id: int, user: User) -> Reservation:
    room = session.get(Room, room_id)
    if room is None or not room.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aktif oda bulunamadı")
    now = clock.now()
    start = datetime.combine(now.date() - timedelta(days=1), room.open_time)
    room_minutes = int(
        (datetime.combine(now.date(), room.close_time) - datetime.combine(now.date(), room.open_time)).total_seconds()
        // 60
    )
    duration = timedelta(minutes=min(room.slot_minutes, room_minutes))
    end = start + duration
    reservation = Reservation(
        user_id=user.id,
        room_id=room.id,
        start_time=start,
        end_time=end,
        seat_number=1 if room.booking_mode == BookingMode.shared else None,
        status=ReservationStatus.completed,
        checked_in_at=start + min(timedelta(minutes=5), end - start),
        is_demo=True,
        created_at=now,
    )
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def list_issues(session: Session, resolved: bool = False) -> list[MaintenanceIssue]:
    return session.exec(
        select(MaintenanceIssue)
        .where(MaintenanceIssue.is_resolved == resolved)
        .order_by(MaintenanceIssue.created_at.desc())
    ).all()


def resolve_issue(session: Session, issue_id: int, now: datetime | None = None) -> MaintenanceIssue:
    issue = session.get(MaintenanceIssue, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arıza bildirimi bulunamadı")
    if not issue.is_resolved:
        issue.is_resolved = True
        issue.resolved_at = now or clock.now()
        session.add(issue)
        session.commit()
        session.refresh(issue)
    return issue
