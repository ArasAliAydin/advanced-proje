from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.models import WaitlistEntry, WaitlistStatus
from app.schemas import WaitlistCreate, WaitlistRead
from app.services import waitlist_service

router = APIRouter(prefix="/waitlist", tags=["Bekleme Listesi"])


def to_read(session, entry: WaitlistEntry) -> WaitlistRead:
    return WaitlistRead.model_validate(entry).model_copy(
        update={"position": waitlist_service.position(session, entry)}
    )


@router.post("", response_model=WaitlistRead, status_code=status.HTTP_201_CREATED)
def join_waitlist(data: WaitlistCreate, session: SessionDep, user: CurrentUser):
    """Dolu bir slot için sıraya girer. Slot boşalınca rezervasyon otomatik oluşturulur."""
    entry = waitlist_service.join(session, user, data.room_id, data.start_time, data.end_time)
    return to_read(session, entry)


@router.get("/me", response_model=list[WaitlistRead])
def my_waitlist(session: SessionDep, user: CurrentUser):
    stmt = select(WaitlistEntry).where(WaitlistEntry.user_id == user.id).order_by(WaitlistEntry.start_time)
    return [to_read(session, e) for e in session.exec(stmt).all()]


@router.get("", response_model=list[WaitlistRead])
def list_waitlist(
    session: SessionDep, _: AdminUser, room_id: int | None = None, status_filter: WaitlistStatus | None = None
):
    """[Admin] Tüm bekleme listesi kayıtları."""
    stmt = select(WaitlistEntry).order_by(WaitlistEntry.created_at)
    if room_id:
        stmt = stmt.where(WaitlistEntry.room_id == room_id)
    if status_filter:
        stmt = stmt.where(WaitlistEntry.status == status_filter)
    return [to_read(session, e) for e in session.exec(stmt).all()]


@router.delete("/{entry_id}", response_model=WaitlistRead)
def leave_waitlist(entry_id: int, session: SessionDep, user: CurrentUser):
    entry = session.get(WaitlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bekleme listesi kaydı bulunamadı")
    return to_read(session, waitlist_service.leave(session, entry, user))
