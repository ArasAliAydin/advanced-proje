from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from app.core import clock
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.schemas import OccupancyCell, RoomStats, Summary
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["Analitik"])


def _resolve(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Varsayılan aralık: son 30 gün."""
    date_to = date_to or clock.now().date()
    date_from = date_from or date_to - timedelta(days=29)
    if date_from > date_to or (date_to - date_from).days > 366:
        raise HTTPException(422, "Geçersiz tarih aralığı (en fazla 1 yıl)")
    return date_from, date_to


@router.get("/occupancy/heatmap", response_model=list[OccupancyCell])
def occupancy_heatmap(
    session: SessionDep, _: CurrentUser, date_from: date | None = None, date_to: date | None = None,
    room_id: int | None = None,
):
    """Haftanın günü × saat bazında doluluk matrisi (ısı haritası verisi)."""
    return analytics.heatmap(session, *_resolve(date_from, date_to), room_id)


@router.get("/occupancy/hourly", response_model=list[OccupancyCell])
def occupancy_hourly(
    session: SessionDep, _: CurrentUser, date_from: date | None = None, date_to: date | None = None,
    room_id: int | None = None,
):
    """Günün saatlerine göre doluluk: en sakin/yoğun saatler."""
    return analytics.by_hour(session, *_resolve(date_from, date_to), room_id)


@router.get("/occupancy/daily", response_model=list[OccupancyCell])
def occupancy_daily(
    session: SessionDep, _: CurrentUser, date_from: date | None = None, date_to: date | None = None,
    room_id: int | None = None,
):
    """Haftanın günlerine göre doluluk."""
    return analytics.by_weekday(session, *_resolve(date_from, date_to), room_id)


@router.get("/rooms", response_model=list[RoomStats])
def room_statistics(session: SessionDep, _: AdminUser, date_from: date | None = None, date_to: date | None = None):
    """[Admin] Oda bazında kullanım, iptal ve no-show istatistikleri."""
    return analytics.room_stats(session, *_resolve(date_from, date_to))


@router.get("/summary", response_model=Summary)
def summary(session: SessionDep, _: AdminUser, date_from: date | None = None, date_to: date | None = None):
    """[Admin] Genel özet rapor."""
    return analytics.summary(session, *_resolve(date_from, date_to), clock.now())
