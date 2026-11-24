"""Oda puanlama ve arıza bildirimi API'leri."""
from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.schemas import (
    DemoReservationCreate,
    MaintenanceIssueCreate,
    MaintenanceIssueRead,
    ReservationRead,
    RoomDirectRatingRead,
    RoomRatingCreate,
    RoomRatingRead,
)
from app.services import feedback

router = APIRouter(prefix="/feedback", tags=["Geri Bildirim"])


@router.get("/demo-mode")
def demo_mode(_: CurrentUser) -> dict[str, bool]:
    return {"enabled": settings.DEMO_MODE_ENABLED}


@router.post(
    "/demo-reservations",
    response_model=ReservationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_demo_reservation(data: DemoReservationCreate, session: SessionDep, user: CurrentUser):
    if not settings.DEMO_MODE_ENABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sunum demo modu etkin değil")
    return feedback.create_demo_reservation(session, data.room_id, user)


@router.post(
    "/rooms/{room_id}/rating",
    response_model=RoomDirectRatingRead,
)
def rate_room(room_id: int, data: RoomRatingCreate, session: SessionDep, user: CurrentUser):
    return feedback.rate_room(session, room_id, user, data.rating, data.comment)


@router.get("/room-ratings/me", response_model=list[RoomDirectRatingRead])
def my_room_ratings(session: SessionDep, user: CurrentUser):
    return feedback.list_my_room_ratings(session, user)


@router.post(
    "/reservations/{reservation_id}/rating",
    response_model=RoomRatingRead,
    status_code=status.HTTP_201_CREATED,
)
def rate_reservation(reservation_id: int, data: RoomRatingCreate, session: SessionDep, user: CurrentUser):
    return feedback.submit_rating(session, reservation_id, user, data.rating, data.comment)


@router.post(
    "/reservations/{reservation_id}/issues",
    response_model=MaintenanceIssueRead,
    status_code=status.HTTP_201_CREATED,
)
def report_issue(reservation_id: int, data: MaintenanceIssueCreate, session: SessionDep, user: CurrentUser):
    return feedback.submit_issue(session, reservation_id, user, data.description)


@router.get("/me", response_model=list[RoomRatingRead])
def my_ratings(session: SessionDep, user: CurrentUser):
    return feedback.list_my_ratings(session, user)


@router.get("/admin/issues", response_model=list[MaintenanceIssueRead])
def admin_issues(
    session: SessionDep,
    _: AdminUser,
    resolved: bool = Query(False),
):
    return feedback.list_issues(session, resolved)


@router.patch("/admin/issues/{issue_id}/resolve", response_model=MaintenanceIssueRead)
def resolve_admin_issue(issue_id: int, session: SessionDep, _: AdminUser):
    return feedback.resolve_issue(session, issue_id)
