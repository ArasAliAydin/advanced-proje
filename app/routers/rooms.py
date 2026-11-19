from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from app.core import clock
from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.models import Room, RoomType
from app.schemas import RoomAvailability, RoomCreate, RoomRead, RoomUpdate, SlotRead
from app.services import holidays, scheduling
from app.services import reservation_service as rs

router = APIRouter(prefix="/rooms", tags=["Odalar"])


def _get_room(session, room_id: int) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Oda bulunamadı")
    return room


def _ensure_unique_name(session, name: str, exclude_id: int | None = None) -> None:
    existing = session.exec(select(Room).where(Room.name == name)).first()
    if existing and existing.id != exclude_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu isimde bir oda zaten var")


def _passes_time_rules(room: Room, start: datetime, end: datetime, now: datetime) -> bool:
    try:
        rs.validate_time_rules(room, start, end, now)
    except rs.BookingError:
        return False
    return True


def _day_block_reason(session, room: Room, day: date, now: datetime) -> str | None:
    """Günün tamamını rezervasyona kapatan neden (kod), yoksa None.

    Tatil sorgusu en sonda: yalnızca rezervasyon yapılabilecek tarih aralığı için harici API'ye gidilir.
    """
    if not room.is_active:
        return "room_inactive"
    if day < now.date():
        return "in_past"
    if day > now.date() + timedelta(days=settings.MAX_ADVANCE_DAYS):
        return "too_far"
    if holidays.holiday_name(session, day):
        return "holiday"
    return None


@router.get("", response_model=list[RoomRead])
def list_rooms(
    session: SessionDep,
    _: CurrentUser,
    room_type: RoomType | None = None,
    min_capacity: int = Query(1, ge=1),
    include_inactive: bool = False,
):
    stmt = select(Room).where(Room.capacity >= min_capacity).order_by(Room.name)
    if room_type:
        stmt = stmt.where(Room.room_type == room_type)
    if not include_inactive:
        stmt = stmt.where(Room.is_active == True)  # noqa: E712
    return session.exec(stmt).all()


@router.get("/available", response_model=list[RoomAvailability])
def available_rooms(
    session: SessionDep,
    _: CurrentUser,
    start_time: datetime,
    end_time: datetime,
    min_capacity: int = Query(1, ge=1),
):
    """Verilen aralıkta rezerve edilebilecek odaları (kalan koltuk sayısıyla) listeler."""
    start, end = clock.to_local_naive(start_time), clock.to_local_naive(end_time)
    now = clock.now()
    rooms = session.exec(select(Room).where(Room.is_active == True, Room.capacity >= min_capacity)).all()  # noqa: E712
    candidates = [room for room in rooms if _passes_time_rules(room, start, end, now)]
    if not candidates or holidays.holiday_name(session, start.date()):
        return []
    result = []
    for room in candidates:
        remaining = rs.remaining_seats(session, room, start, end)
        if remaining > 0:
            result.append(RoomAvailability(room=RoomRead.model_validate(room), remaining_seats=remaining))
    return result


@router.get("/{room_id}", response_model=RoomRead)
def get_room(room_id: int, session: SessionDep, _: CurrentUser):
    return _get_room(session, room_id)


@router.get("/{room_id}/availability", response_model=list[SlotRead])
def room_availability(room_id: int, day: date, session: SessionDep, _: CurrentUser):
    """Odanın o günkü tüm zaman dilimlerini ve her dilimde kalan yer sayısını döndürür.

    `available` rezervasyon kurallarıyla tutarlıdır: tatil günleri, geçmiş ve
    `MAX_ADVANCE_DAYS` ötesi müsait görünmez; nedeni `reason` alanındadır.
    """
    room = _get_room(session, room_id)
    opening = datetime.combine(day, room.open_time)
    closing = datetime.combine(day, room.close_time)
    busy = [(r.start_time, r.end_time) for r in rs.occupying_reservations(session, room.id, opening, closing)]
    total, now = rs.seats_limit(room), clock.now()
    day_reason = _day_block_reason(session, room, day, now)
    step = timedelta(minutes=room.slot_minutes)
    slots, start = [], opening
    while start + step <= closing:
        end = start + step
        remaining = total - scheduling.peak_concurrency(busy, start, end)
        reason = day_reason or ("in_past" if start <= now else "slot_full" if remaining <= 0 else None)
        slots.append(
            SlotRead(
                start_time=start,
                end_time=end,
                total_seats=total,
                remaining_seats=remaining,
                available=reason is None,
                reason=reason,
            )
        )
        start = end
    return slots


@router.post("", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
def create_room(data: RoomCreate, session: SessionDep, _: AdminUser):
    _ensure_unique_name(session, data.name)
    room = Room(**data.model_dump())
    session.add(room)
    session.commit()
    session.refresh(room)
    return room


@router.patch("/{room_id}", response_model=RoomRead)
def update_room(room_id: int, data: RoomUpdate, session: SessionDep, _: AdminUser):
    """Alanları günceller. `is_active: false` gönderilirse oda `DELETE` ile aynı şekilde kapatılır."""
    room = _get_room(session, room_id)
    # null gönderilen alan "değiştirme" sayılır; kolonların hiçbiri NULL kabul etmez
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        _ensure_unique_name(session, changes["name"], exclude_id=room.id)
    # Doğrulama, nesne değiştirilmeden önce: reddedilen istek oturumda yarım değişiklik bırakmaz
    if changes.get("close_time", room.close_time) <= changes.get("open_time", room.open_time):
        raise HTTPException(422, "close_time, open_time'dan sonra olmalı")
    closing = room.is_active and changes.get("is_active") is False
    for key, value in changes.items():
        setattr(room, key, value)
    if closing:
        rs.close_room(session, room, clock.now())
    else:
        session.add(room)
        session.commit()
    session.refresh(room)
    return room


@router.delete("/{room_id}", response_model=RoomRead)
def deactivate_room(room_id: int, session: SessionDep, _: AdminUser):
    """Odayı silmez, rezervasyona kapatır (geçmiş kayıtlar ve analitik korunur).

    Henüz başlamamış rezervasyonlar cezasız iptal edilir ve sahiplerine e-posta gider.
    """
    room = _get_room(session, room_id)
    rs.close_room(session, room, clock.now())
    session.refresh(room)
    return room
