from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlmodel import select

from app.core import clock
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.models import Reservation, ReservationStatus, Role, Room, User
from app.schemas import CheckinRequest, ReservationCreate, ReservationRead
from app.services import exports
from app.services import reservation_service as rs

router = APIRouter(prefix="/reservations", tags=["Rezervasyonlar"])
checkin_router = APIRouter(prefix="/checkin", tags=["Check-in"])


def to_read(session, reservation: Reservation) -> ReservationRead:
    room = session.get(Room, reservation.room_id)
    return ReservationRead.model_validate(reservation).model_copy(update={"room_name": room.name if room else None})


def _get_owned(session, reservation_id: int, user: User) -> Reservation:
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rezervasyon bulunamadı")
    if user.role != Role.admin and reservation.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu rezervasyon size ait değil")
    return reservation


@router.post("", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
def create_reservation(data: ReservationCreate, session: SessionDep, user: CurrentUser):
    """Rezervasyon oluşturur. Slot doluysa 409 `slot_full` döner; bu durumda bekleme listesine katılınabilir."""
    reservation = rs.book(session, user, data.room_id, data.start_time, data.end_time)
    return to_read(session, reservation)


@router.get("", response_model=list[ReservationRead])
def list_all_reservations(
    session: SessionDep,
    _: AdminUser,
    room_id: int | None = None,
    user_id: int | None = None,
    status_filter: ReservationStatus | None = Query(None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """[Admin] Tüm rezervasyonlar, filtrelenebilir."""
    stmt = select(Reservation).order_by(Reservation.start_time.desc()).limit(limit).offset(offset)
    if room_id:
        stmt = stmt.where(Reservation.room_id == room_id)
    if user_id:
        stmt = stmt.where(Reservation.user_id == user_id)
    if status_filter:
        stmt = stmt.where(Reservation.status == status_filter)
    if date_from:
        stmt = stmt.where(Reservation.start_time >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(Reservation.start_time < datetime.combine(date_to, datetime.min.time()) + timedelta(days=1))
    return [to_read(session, r) for r in session.exec(stmt).all()]


@router.get("/me", response_model=list[ReservationRead])
def my_reservations(
    session: SessionDep,
    user: CurrentUser,
    status_filter: ReservationStatus | None = Query(None, alias="status"),
    upcoming: bool = False,
):
    stmt = select(Reservation).where(Reservation.user_id == user.id).order_by(Reservation.start_time)
    if status_filter:
        stmt = stmt.where(Reservation.status == status_filter)
    if upcoming:
        stmt = stmt.where(Reservation.end_time > clock.now())
    return [to_read(session, r) for r in session.exec(stmt).all()]


@router.get("/me/calendar.ics", response_class=Response)
def my_calendar(session: SessionDep, user: CurrentUser):
    """Yaklaşan tüm rezervasyonları tek bir .ics takvim dosyası olarak indirir."""
    stmt = select(Reservation).where(
        Reservation.user_id == user.id,
        Reservation.end_time > clock.now(),
        Reservation.status.in_(rs.OCCUPYING),
    )
    items = [(r, session.get(Room, r.room_id)) for r in session.exec(stmt).all()]
    return Response(
        exports.build_ics(items),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="studyspot.ics"'},
    )


@router.get("/{reservation_id}", response_model=ReservationRead)
def get_reservation(reservation_id: int, session: SessionDep, user: CurrentUser):
    return to_read(session, _get_owned(session, reservation_id, user))


@router.delete("/{reservation_id}", response_model=ReservationRead)
def cancel_reservation(reservation_id: int, session: SessionDep, user: CurrentUser, reason: str | None = None):
    """İptal eder ve boşalan slotu bekleme listesindeki ilk uygun kişiye otomatik atar.

    Başlangıca `LATE_CANCEL_MINUTES` dakikadan az kala yapılan iptal ceza puanı getirir.
    """
    reservation = _get_owned(session, reservation_id, user)
    return to_read(session, rs.cancel(session, reservation, user, reason))


@router.get("/{reservation_id}/qr", response_class=Response)
def reservation_qr(reservation_id: int, session: SessionDep, user: CurrentUser):
    """Check-in kodunu içeren QR görseli (PNG)."""
    reservation = _get_owned(session, reservation_id, user)
    return Response(exports.qr_png(reservation.checkin_code), media_type="image/png")


@router.get("/{reservation_id}/ics", response_class=Response)
def reservation_ics(reservation_id: int, session: SessionDep, user: CurrentUser):
    reservation = _get_owned(session, reservation_id, user)
    return Response(
        exports.build_ics([(reservation, session.get(Room, reservation.room_id))]),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="reservation-{reservation.id}.ics"'},
    )


@checkin_router.post("", response_model=ReservationRead)
def check_in(data: CheckinRequest, session: SessionDep, user: CurrentUser):
    """QR'dan okunan kodla check-in yapar (rezervasyon sahibi veya görevli/admin).

    Pencere: başlangıçtan `CHECKIN_OPEN_MINUTES_BEFORE` dk önce açılır,
    `CHECKIN_GRACE_MINUTES` dk sonra kapanır. Süreyi kaçıran no-show sayılır.
    """
    return to_read(session, rs.check_in(session, data.code.strip(), user))
