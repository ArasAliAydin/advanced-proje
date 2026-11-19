"""Harici API entegrasyonu: resmi tatiller (https://date.nager.at), DB'de önbelleklenir.

API'ye ulaşılamazsa sistem "fail-open" davranır: tatil kontrolü atlanır, rezervasyon engellenmez.
"""
import logging
import time
from datetime import date

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Holiday

logger = logging.getLogger("studyspot.holidays")

NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
_RETRY_AFTER_SECONDS = 600
_last_failure: dict[int, float] = {}


def fetch_holidays(year: int, country: str) -> list[dict]:
    response = httpx.get(NAGER_URL.format(year=year, country=country), timeout=5)
    response.raise_for_status()
    return response.json()


def ensure_year_cached(session: Session, year: int) -> bool:
    """Yılın tatilleri önbellekte yoksa API'den çeker. Başarılıysa True."""
    if session.exec(select(Holiday).where(Holiday.year == year).limit(1)).first():
        return True
    if time.monotonic() - _last_failure.get(year, float("-inf")) < _RETRY_AFTER_SECONDS:
        return False
    try:
        items = fetch_holidays(year, settings.HOLIDAY_COUNTRY)
    except Exception as exc:
        logger.warning("Tatil API'sine ulaşılamadı (%s): %s", year, exc)
        _last_failure[year] = time.monotonic()
        return False
    seen: set[date] = set()
    for item in items:
        day = date.fromisoformat(item["date"])
        if day in seen:
            continue
        seen.add(day)
        session.add(Holiday(day=day, year=year, name=item.get("localName") or item.get("name") or "Resmi tatil"))
    session.commit()
    return bool(seen)


def holiday_name(session: Session, day: date) -> str | None:
    """Gün resmi tatilse adını, değilse (veya kontrol kapalı/başarısızsa) None döndürür."""
    if not settings.HOLIDAY_CHECK_ENABLED or not ensure_year_cached(session, day.year):
        return None
    holiday = session.exec(select(Holiday).where(Holiday.day == day)).first()
    return holiday.name if holiday else None


def list_holidays(session: Session, year: int) -> list[Holiday]:
    ensure_year_cached(session, year)
    return list(session.exec(select(Holiday).where(Holiday.year == year).order_by(Holiday.day)).all())
