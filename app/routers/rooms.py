from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select

from app.core import clock
from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.models import BookingMode, Room, RoomDirectRating, RoomRating, RoomType
from app.schemas import (
    OccupancyCell,
    RoomAvailability,
    RoomCreate,
    RoomRead,
    RoomUpdate,
    SeatMapRead,
    SeatRead,
    SlotRead,
)
from app.services import holidays, scheduling, suggestions
from app.services import reservation_service as rs

router = APIRouter(prefix="/rooms", tags=["Odalar"])


def _get_room(session, room_id: int) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Oda bulunamadı")
    return room


def _room_reads(session, rooms: list[Room]) -> list[RoomRead]:
    room_ids = [room.id for room in rooms]
    ratings = {
        room_id: [float(average) * count, count]
        for room_id, average, count in session.exec(
            select(RoomRating.room_id, func.avg(RoomRating.rating), func.count(RoomRating.id))
            .where(RoomRating.room_id.in_(room_ids))
            .group_by(RoomRating.room_id)
        ).all()
    } if room_ids else {}
    if room_ids:
        for room_id, average, count in session.exec(
            select(RoomDirectRating.room_id, func.avg(RoomDirectRating.rating), func.count(RoomDirectRating.id))
            .where(RoomDirectRating.room_id.in_(room_ids))
            .group_by(RoomDirectRating.room_id)
        ).all():
            total = ratings.setdefault(room_id, [0.0, 0])
            total[0] += float(average) * count
            total[1] += count
    return [
        RoomRead.model_validate(room).model_copy(
            update={"average_rating": ratings[room.id][0] / ratings[room.id][1] if room.id in ratings else None}
        )
        for room in rooms
    ]


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
    return _room_reads(session, session.exec(stmt).all())


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
    room_reads = {room_read.id: room_read for room_read in _room_reads(session, candidates)}
    for room in candidates:
        remaining = rs.remaining_seats(session, room, start, end)
        if remaining > 0:
            result.append(RoomAvailability(room=room_reads[room.id], remaining_seats=remaining))
    return result


@router.get("/{room_id}", response_model=RoomRead)
def get_room(room_id: int, session: SessionDep, _: CurrentUser):
    return _room_reads(session, [_get_room(session, room_id)])[0]


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


@router.get("/{room_id}/seats", response_model=SeatMapRead)
def room_seats(room_id: int, start_time: datetime, end_time: datetime, session: SessionDep, user: CurrentUser):
    """Koltuk bazlı (shared) odanın koltuk haritası: aralığın tamamında hangi koltuklar boş.

    Rezervasyonda `seat_number` ile koltuk seçmek için kullanılır. Exclusive odalarda 400 `seat_not_applicable`.
    """
    room = _get_room(session, room_id)
    start, end = clock.to_local_naive(start_time), clock.to_local_naive(end_time)
    if end <= start:
        raise rs.BookingError("invalid_interval", "Bitiş saati başlangıçtan sonra olmalı")
    if room.booking_mode != BookingMode.shared:
        raise rs.BookingError("seat_not_applicable", "Bu oda tümüyle rezerve edilir, koltuk seçilmez")
    occupying = rs.occupying_reservations(session, room.id, start, end)
    taken = {r.seat_number for r in occupying if r.seat_number is not None}
    mine = {r.seat_number for r in occupying if r.user_id == user.id and r.seat_number is not None}
    return SeatMapRead(
        room_id=room.id,
        capacity=room.capacity,
        seats_per_row=room.seats_per_row,
        start_time=start,
        end_time=end,
        remaining_seats=max(0, rs.remaining_seats(session, room, start, end)),
        seats=[SeatRead(number=n, available=n not in taken, mine=n in mine) for n in range(1, room.capacity + 1)],
    )


@router.get("/{room_id}/quiet-hours", response_model=list[OccupancyCell])
def room_quiet_hours(
    room_id: int,
    session: SessionDep,
    _: CurrentUser,
    weekday: int | None = Query(None, ge=0, le=6, description="0 = Pazartesi; boşsa tüm günler"),
    limit: int = Query(5, ge=1, le=24),
):
    """Odanın geçmiş doluluğa göre en sakin saatleri (en sakinden başlayarak).

    Son `SUGGEST_HISTORY_DAYS` gün (bugün hariç) kullanılır.
    """
    room = _get_room(session, room_id)
    return suggestions.quiet_hours(session, room, clock.now(), weekday, limit)


@router.post("", response_model=RoomRead, status_code=status.HTTP_201_CREATED)
def create_room(data: RoomCreate, session: SessionDep, _: AdminUser):
    _ensure_unique_name(session, data.name)
    room = Room(**data.model_dump())
    session.add(room)
    session.commit()
    session.refresh(room)
    return _room_reads(session, [room])[0]


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
    return _room_reads(session, [room])[0]


@router.delete("/{room_id}", response_model=RoomRead)
def deactivate_room(room_id: int, session: SessionDep, _: AdminUser):
    """Odayı silmez, rezervasyona kapatır (geçmiş kayıtlar ve analitik korunur).

    Henüz başlamamış rezervasyonlar cezasız iptal edilir ve sahiplerine e-posta gider.
    """
    room = _get_room(session, room_id)
    rs.close_room(session, room, clock.now())
    session.refresh(room)
    return _room_reads(session, [room])[0]
