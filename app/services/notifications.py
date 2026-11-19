"""E-posta bildirimi. Her bildirim EmailLog tablosuna yazılır; EMAIL_BACKEND=smtp ise gerçekten gönderilir."""
import logging
import smtplib
from email.message import EmailMessage

from sqlmodel import Session

from app.core.config import settings
from app.models import EmailLog, User

logger = logging.getLogger("studyspot.email")


def _send_smtp(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def notify(session: Session, user: User, subject: str, body: str, kind: str) -> EmailLog:
    """Bildirimi kaydeder (commit çağırana aittir) ve backend'e göre gönderir."""
    log = EmailLog(user_id=user.id, to_email=user.email, subject=subject, body=body, kind=kind)
    if settings.EMAIL_BACKEND == "smtp" and settings.SMTP_HOST:
        try:
            _send_smtp(user.email, subject, body)
            log.status = "sent"
        except Exception as exc:  # e-posta hatası iş akışını bozmamalı
            logger.warning("E-posta gönderilemedi (%s): %s", user.email, exc)
            log.status, log.error = "failed", str(exc)[:500]
    else:
        logger.info("[e-posta:%s] %s -> %s", kind, subject, user.email)
    session.add(log)
    return log
