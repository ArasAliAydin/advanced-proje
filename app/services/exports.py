"""Dışa aktarma: .ics takvim dosyası ve check-in QR kodu."""
import io
from datetime import datetime, timezone

import segno

from app.core import clock
from app.core.config import settings
from app.models import Reservation, ReservationStatus, Room


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=clock.tz()).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(items: list[tuple[Reservation, Room]]) -> str:
    """RFC 5545 uyumlu takvim. Google Calendar / Outlook / Apple Takvim içe aktarabilir."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StudySpot//CEN3001//TR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for reservation, room in items:
        cancelled = reservation.status in (ReservationStatus.cancelled, ReservationStatus.no_show)
        lines += [
            "BEGIN:VEVENT",
            f"UID:reservation-{reservation.id}@studyspot",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_utc(reservation.start_time)}",
            f"DTEND:{_ics_utc(reservation.end_time)}",
            f"SUMMARY:{_ics_escape('StudySpot: ' + room.name)}",
            f"LOCATION:{_ics_escape(room.location)}",
            f"DESCRIPTION:{_ics_escape('Rezervasyon #%d. Check-in icin QR kodunuzu okutun.' % reservation.id)}",
            f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:StudySpot rezervasyonunuz yaklasiyor",
            f"TRIGGER:-PT{settings.REMINDER_MINUTES_BEFORE}M",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def qr_png(payload: str) -> bytes:
    buffer = io.BytesIO()
    segno.make(payload, error="m").save(buffer, kind="png", scale=8, border=2)
    return buffer.getvalue()
