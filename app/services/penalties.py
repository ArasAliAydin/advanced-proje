"""Ceza puanı sistemi: eşik aşılınca kullanıcı geçici olarak rezervasyon yapamaz."""
from datetime import datetime, timedelta

from sqlmodel import Session

from app.core.config import settings
from app.models import PenaltyLog, User
from app.services.notifications import notify


def add_penalty(
    session: Session, user: User, points: int, reason: str, now: datetime, reservation_id: int | None = None
) -> PenaltyLog:
    log = PenaltyLog(user_id=user.id, reservation_id=reservation_id, points=points, reason=reason, created_at=now)
    session.add(log)
    user.penalty_points += points
    if user.penalty_points >= settings.PENALTY_BAN_THRESHOLD:
        user.banned_until = now + timedelta(days=settings.BAN_DAYS)
        user.penalty_points = 0  # ceza çekildi, sayaç sıfırlanır
        notify(
            session,
            user,
            "StudySpot: Rezervasyon hakkınız askıya alındı",
            f"Ceza puanı eşiğini ({settings.PENALTY_BAN_THRESHOLD}) aştığınız için "
            f"{user.banned_until:%d.%m.%Y %H:%M} tarihine kadar yeni rezervasyon yapamazsınız.",
            "ban",
        )
    session.add(user)
    return log
