"""Zaman aralığı algoritmaları (saf fonksiyonlar, DB'den bağımsız).

Aralıklar yarı açıktır: [start, end). Yani 10:00-11:00 ile 11:00-12:00 çakışmaz.
"""
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta

Interval = tuple[datetime, datetime]


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def peak_concurrency(intervals: Iterable[Interval], window_start: datetime, window_end: datetime) -> int:
    """Pencere içinde aynı anda aktif olan en fazla aralık sayısı (sweep-line, O(n log n)).

    Koltuk bazlı salonlarda "bu aralığın herhangi bir anında salon dolu mu?" sorusunu
    yanıtlar: yalnızca çakışan rezervasyonları saymak yetmez, çünkü 10-11 ve 11-12
    rezervasyonları 10-12 penceresiyle çakışır ama aynı koltuğu art arda kullanabilir.
    """
    events: list[tuple[datetime, int]] = []
    for start, end in intervals:
        start, end = max(start, window_start), min(end, window_end)
        if start < end:
            events.append((start, 1))
            events.append((end, -1))
    # Aynı anda biten (-1) başlayandan (+1) önce işlenir -> yarı açık aralık semantiği
    events.sort()
    peak = current = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def hour_buckets(start: datetime, end: datetime) -> Iterator[tuple[date, int, float]]:
    """Aralığı saat dilimlerine böler: (gün, saat, o saate düşen süre [saat])."""
    cur = start
    while cur < end:
        nxt = min(end, cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        yield cur.date(), cur.hour, (nxt - cur).total_seconds() / 3600
        cur = nxt


def week_bounds(day: date) -> tuple[datetime, datetime]:
    """Günün ait olduğu haftanın [Pazartesi 00:00, sonraki Pazartesi 00:00) aralığı."""
    monday = day - timedelta(days=day.weekday())
    start = datetime.combine(monday, datetime.min.time())
    return start, start + timedelta(days=7)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time())
    return start, start + timedelta(days=1)
