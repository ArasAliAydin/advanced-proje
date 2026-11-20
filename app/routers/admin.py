"""Admin endpoint'leri: kullanıcı yönetimi, cezalar, e-posta günlüğü, raporlar, görev tetikleme."""
import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import select

from app.core.deps import AdminUser, SessionDep, require_admin
from app.models import EmailLog, PenaltyLog, Reservation, Room, User
from app.schemas import EmailLogRead, HolidayRead, PenaltyRead, UserAdminUpdate, UserRead
from app.services import holidays, jobs

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


def _csv_safe(value: str) -> str:
    """Excel'in hücreyi formül olarak çalıştırmasını engeller (CSV injection)."""
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def _get_user(session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    return user


@router.get("/users", response_model=list[UserRead])
def list_users(session: SessionDep, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return session.exec(select(User).order_by(User.id).limit(limit).offset(offset)).all()


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserAdminUpdate, session: SessionDep, admin: AdminUser):
    """Rol değiştirir veya hesabı aktif/pasif yapar."""
    user = _get_user(session, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi rolünüzü veya durumunuzu değiştiremezsiniz")
    for key, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, key, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/users/{user_id}/reset-penalty", response_model=UserRead)
def reset_penalty(user_id: int, session: SessionDep):
    """Ceza puanını ve varsa rezervasyon yasağını kaldırır."""
    user = _get_user(session, user_id)
    user.penalty_points = 0
    user.banned_until = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/penalties", response_model=list[PenaltyRead])
def list_penalties(session: SessionDep, user_id: int | None = None, limit: int = Query(100, ge=1, le=500)):
    stmt = select(PenaltyLog).order_by(PenaltyLog.created_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(PenaltyLog.user_id == user_id)
    return session.exec(stmt).all()


@router.get("/emails", response_model=list[EmailLogRead])
def list_emails(session: SessionDep, kind: str | None = None, limit: int = Query(50, ge=1, le=500)):
    """Gönderilen/kaydedilen bildirim e-postaları (demo için kullanışlı)."""
    stmt = select(EmailLog).order_by(EmailLog.id.desc()).limit(limit)
    if kind:
        stmt = stmt.where(EmailLog.kind == kind)
    return session.exec(stmt).all()


@router.post("/jobs/run")
def run_jobs(session: SessionDep) -> dict[str, int]:
    """Zamanlanmış görevleri (no-show, hatırlatma, tamamlama, bekleme listesi temizliği) hemen çalıştırır."""
    return jobs.run_all(session)


@router.get("/holidays/{year}", response_model=list[HolidayRead])
def list_holidays(year: int, session: SessionDep):
    """Harici API'den çekilip önbelleklenen resmi tatiller."""
    return holidays.list_holidays(session, year)


@router.get("/reports/reservations.csv", response_class=Response)
def export_reservations(session: SessionDep, date_from: date, date_to: date):
    """Tarih aralığındaki rezervasyonları CSV olarak dışa aktarır."""
    lo = datetime.combine(date_from, datetime.min.time())
    hi = datetime.combine(date_to, datetime.min.time()) + timedelta(days=1)
    stmt = (
        select(Reservation, User, Room)
        .join(User, User.id == Reservation.user_id)
        .join(Room, Room.id == Reservation.room_id)
        .where(Reservation.start_time >= lo, Reservation.start_time < hi)
        .order_by(Reservation.start_time)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "room", "user_email", "user_name", "start_time", "end_time", "status", "source", "checked_in_at", "seat"])
    for r, user, room in session.exec(stmt).all():
        writer.writerow(
            [
                r.id, _csv_safe(room.name), _csv_safe(user.email), _csv_safe(user.full_name),
                r.start_time.isoformat(), r.end_time.isoformat(),
                r.status.value, r.source.value, r.checked_in_at.isoformat() if r.checked_in_at else "",
                r.seat_number or "",
            ]
        )
    return Response(
        "﻿" + buffer.getvalue(),  # BOM: Excel Türkçe karakterleri doğru açsın
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="reservations.csv"'},
    )
