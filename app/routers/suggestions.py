from datetime import datetime

from fastapi import APIRouter, Query

from app.core import clock
from app.core.deps import CurrentUser, SessionDep
from app.schemas import SuggestionRead
from app.services import suggestions

router = APIRouter(prefix="/suggestions", tags=["Öneriler"])


@router.get("", response_model=list[SuggestionRead])
def suggest_slots(
    session: SessionDep,
    user: CurrentUser,
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    limit: int | None = Query(None, ge=1, le=20),
):
    """İstenen slot yerine alınabilecek alternatifler (skora göre azalan).

    Aynı odada aynı gün, aynı süredeki en yakın boş aralıklar ve aynı saatte uygun diğer odalar.
    Her öneri rezervasyon kurallarından (saat, limit, çakışma, kalan koltuk) geçmiştir.
    Skor = zaman yakınlığı + oda tipi/kapasite uyumu + geçmişteki sakinlik (ağırlıklar `.env`'de).
    """
    start, end = clock.to_local_naive(start_time), clock.to_local_naive(end_time)
    return suggestions.suggest(session, user, room_id, start, end, limit=limit)
