"""Tek zaman kaynağı.

Tüm tarih/saatler kampüs yerel saatinde (settings.TIMEZONE) ve tz bilgisi olmadan
(naive) saklanır. Testler `freeze()` ile zamanı sabitleyebilir.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings

_frozen: datetime | None = None


def tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def now() -> datetime:
    if _frozen is not None:
        return _frozen
    return datetime.now(tz()).replace(tzinfo=None, microsecond=0)


def to_local_naive(dt: datetime) -> datetime:
    """Tz'li bir datetime'ı kampüs yerel saatine çevirip tz bilgisini atar."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz()).replace(tzinfo=None)
    return dt


def freeze(dt: datetime) -> None:
    global _frozen
    _frozen = dt


def unfreeze() -> None:
    global _frozen
    _frozen = None
