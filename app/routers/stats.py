"""Kişisel istatistikler ve oda doluluk tahmini endpoint'leri (yalnızca okuma)."""
from datetime import date

from fastapi import APIRouter, HTTPException, status

from app.core import clock
from app.core.deps import CurrentUser, SessionDep
from app.models import Room
from app.schemas import MyStats, RoomForecast
from app.services import stats

router = APIRouter(tags=["İstatistik ve tahmin"])


@router.get("/stats/me", response_model=MyStats)
def my_stats(session: SessionDep, user: CurrentUser):
    """Bu hafta/bugün kullanılan ve kalan saat, katılım ve gelmeme oranı, en çok kullanılan oda ve saat,
    üst üste katılınan hafta sayısı, ceza durumu ve son 8 haftanın saatleri."""
    return stats.my_stats(session, user, clock.now())


@router.get("/rooms/{room_id}/forecast", response_model=RoomForecast)
def room_forecast(room_id: int, day: date, session: SessionDep, _: CurrentUser):
    """Odanın verilen gün için saat saat beklenen doluluğu.

    Aynı haftanın gününün son 4 haftası ağırlıklı ortalanır (yakın hafta daha ağırlıklı: 4-3-2-1);
    o güne şimdiden yapılmış rezervasyonlarla birleştirilir. `best_hours`: en sakin 3 saat.
    Yalnızca bugün ile `MAX_ADVANCE_DAYS` arası; dışında 400 `forecast_range`.
    """
    room = session.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Oda bulunamadı")
    return stats.forecast(session, room, day, clock.now())
