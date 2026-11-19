"""Doluluk analitiği: rezervasyonları saat dilimlerine bölüp kapasiteye oranlar."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlmodel import Session, col, or_, select

from app.models import (
    PenaltyLog,
    Reservation,
    ReservationStatus,
    Room,
    User,
    WaitlistEntry,
)
from app.schemas import OccupancyCell, RoomStats, Summary
from app.services import scheduling
from app.services.reservation_service import COUNTED_FOR_LIMITS, seats_limit

WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
# Doluluk hesabında "kullanılmış" sayılanlar (no-show hariç: koltuk fiilen boş kaldı)
USED = (ReservationStatus.confirmed, ReservationStatus.checked_in, ReservationStatus.completed)

Key = tuple[int, int]  # (haftanın günü, saat)


def _rate(reserved: float, capacity: float) -> float:
    return round(reserved / capacity, 3) if capacity else 0.0


def _range(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    return datetime.combine(d_from, datetime.min.time()), datetime.combine(d_to, datetime.min.time()) + timedelta(days=1)


def _open_fraction(room: Room, hour: int) -> float:
    """Odanın [hour, hour+1) saatinin ne kadarında açık olduğu (0..1)."""
    open_m = room.open_time.hour * 60 + room.open_time.minute
    close_m = room.close_time.hour * 60 + room.close_time.minute
    return max(0, min(close_m, hour * 60 + 60) - max(open_m, hour * 60)) / 60


def _rooms(session: Session, room_id: int | None, d_from: date, d_to: date) -> list[Room]:
    """Aktif odalar ve aralıkta rezervasyonu olan pasif odalar.

    Pasife alınan odanın geçmişi raporlardan düşmemeli. Pasife alınma tarihi tutulmadığı
    için böyle bir odanın kapasitesi aralığın tamamında sayılır.
    """
    if room_id:
        return list(session.exec(select(Room).where(Room.id == room_id)).all())
    lo, hi = _range(d_from, d_to)
    used = select(Reservation.room_id).where(Reservation.start_time >= lo, Reservation.start_time < hi)
    stmt = select(Room).where(or_(Room.is_active == True, col(Room.id).in_(used)))  # noqa: E712
    return list(session.exec(stmt).all())


def _reservations(session: Session, rooms: list[Room], d_from: date, d_to: date, statuses) -> list[Reservation]:
    lo, hi = _range(d_from, d_to)
    stmt = select(Reservation).where(
        col(Reservation.room_id).in_([r.id for r in rooms]),
        col(Reservation.status).in_(statuses),
        Reservation.start_time >= lo,
        Reservation.start_time < hi,
    )
    return list(session.exec(stmt).all())


def _matrix(session: Session, d_from: date, d_to: date, room_id: int | None) -> tuple[dict[Key, float], dict[Key, float]]:
    rooms = _rooms(session, room_id, d_from, d_to)
    reserved: dict[Key, float] = defaultdict(float)
    capacity: dict[Key, float] = defaultdict(float)
    hourly_capacity = [sum(_open_fraction(room, h) * seats_limit(room) for room in rooms) for h in range(24)]
    day = d_from
    while day <= d_to:
        for hour, cap in enumerate(hourly_capacity):
            if cap:
                capacity[(day.weekday(), hour)] += cap
        day += timedelta(days=1)
    for reservation in _reservations(session, rooms, d_from, d_to, USED):
        for bucket_day, hour, hours in scheduling.hour_buckets(reservation.start_time, reservation.end_time):
            reserved[(bucket_day.weekday(), hour)] += hours
    return reserved, capacity


def heatmap(session: Session, d_from: date, d_to: date, room_id: int | None = None) -> list[OccupancyCell]:
    reserved, capacity = _matrix(session, d_from, d_to, room_id)
    return [
        OccupancyCell(
            weekday=wd,
            weekday_name=WEEKDAYS[wd],
            hour=hour,
            reserved_hours=round(reserved[(wd, hour)], 2),
            capacity_hours=round(cap, 2),
            occupancy_rate=_rate(reserved[(wd, hour)], cap),
        )
        for (wd, hour), cap in sorted(capacity.items())
    ]


def _aggregate(session: Session, d_from: date, d_to: date, room_id: int | None, index: int) -> dict[int, list[float]]:
    reserved, capacity = _matrix(session, d_from, d_to, room_id)
    totals: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for key, cap in capacity.items():
        totals[key[index]][0] += reserved[key]
        totals[key[index]][1] += cap
    return totals


def by_hour(session: Session, d_from: date, d_to: date, room_id: int | None = None) -> list[OccupancyCell]:
    totals = _aggregate(session, d_from, d_to, room_id, index=1)
    return [
        OccupancyCell(hour=h, reserved_hours=round(r, 2), capacity_hours=round(c, 2), occupancy_rate=_rate(r, c))
        for h, (r, c) in sorted(totals.items())
    ]


def by_weekday(session: Session, d_from: date, d_to: date, room_id: int | None = None) -> list[OccupancyCell]:
    totals = _aggregate(session, d_from, d_to, room_id, index=0)
    return [
        OccupancyCell(
            weekday=wd,
            weekday_name=WEEKDAYS[wd],
            reserved_hours=round(r, 2),
            capacity_hours=round(c, 2),
            occupancy_rate=_rate(r, c),
        )
        for wd, (r, c) in sorted(totals.items())
    ]


def room_stats(session: Session, d_from: date, d_to: date) -> list[RoomStats]:
    days = (d_to - d_from).days + 1
    result = []
    for room in session.exec(select(Room).order_by(Room.name)).all():
        rows = _reservations(session, [room], d_from, d_to, list(ReservationStatus))
        used_hours = sum((r.end_time - r.start_time).total_seconds() / 3600 for r in rows if r.status in USED)
        capacity = sum(_open_fraction(room, h) for h in range(24)) * seats_limit(room) * days
        no_show = sum(r.status == ReservationStatus.no_show for r in rows)
        cancelled = sum(r.status == ReservationStatus.cancelled for r in rows)
        honoured = len(rows) - cancelled
        result.append(
            RoomStats(
                room_id=room.id,
                room_name=room.name,
                total_reservations=len(rows),
                reserved_hours=round(used_hours, 2),
                occupancy_rate=_rate(used_hours, capacity),
                cancelled=cancelled,
                no_show=no_show,
                no_show_rate=_rate(no_show, honoured),
            )
        )
    return result


def summary(session: Session, d_from: date, d_to: date, now: datetime) -> Summary:
    lo, hi = _range(d_from, d_to)
    rooms = _rooms(session, None, d_from, d_to)
    reservations = _reservations(session, rooms, d_from, d_to, list(ReservationStatus))
    by_status: dict[str, int] = defaultdict(int)
    for r in reservations:
        by_status[r.status.value] += 1
    waitlist: dict[str, int] = defaultdict(int)
    for e in session.exec(
        select(WaitlistEntry).where(WaitlistEntry.start_time >= lo, WaitlistEntry.start_time < hi)
    ).all():
        waitlist[e.status.value] += 1
    reserved, capacity = _matrix(session, d_from, d_to, None)
    hours = by_hour(session, d_from, d_to)
    weekdays = by_weekday(session, d_from, d_to)
    busiest_hour = max(hours, key=lambda c: c.occupancy_rate, default=None)
    busiest_day = max(weekdays, key=lambda c: c.occupancy_rate, default=None)
    counted = sum(by_status.get(s.value, 0) for s in COUNTED_FOR_LIMITS)
    users = session.exec(select(User)).all()
    penalties = session.exec(
        select(PenaltyLog).where(PenaltyLog.created_at >= lo, PenaltyLog.created_at < hi)
    ).all()
    total_reserved = sum(reserved.values())
    return Summary(
        date_from=d_from,
        date_to=d_to,
        total_users=len(users),
        total_rooms=sum(room.is_active for room in rooms),
        reservations_by_status=dict(by_status),
        waitlist_by_status=dict(waitlist),
        reserved_hours=round(total_reserved, 2),
        occupancy_rate=_rate(total_reserved, sum(capacity.values())),
        no_show_rate=_rate(by_status.get(ReservationStatus.no_show.value, 0), counted),
        penalty_points_given=sum(p.points for p in penalties),
        banned_users=sum(1 for u in users if u.banned_until and u.banned_until > now),
        busiest_hour=busiest_hour.hour if busiest_hour and busiest_hour.reserved_hours else None,
        busiest_weekday=busiest_day.weekday_name if busiest_day and busiest_day.reserved_hours else None,
    )
