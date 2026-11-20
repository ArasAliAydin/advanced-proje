from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings


def _make_engine(url: str):
    if not url.startswith("sqlite"):
        return create_engine(url)
    connect_args = {"check_same_thread": False}
    if url in ("sqlite://", "sqlite:///:memory:"):
        # Bellek içi DB: tek bağlantı paylaşılmalı (testler)
        return create_engine(url, connect_args=connect_args, poolclass=StaticPool)
    Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


engine = _make_engine(settings.DATABASE_URL)


# create_all mevcut tabloya kolon eklemez. v3'te eklenen kolonlar eski veritabanlarına
# (v1/v2'den kalan SQLite dosyası) burada eklenir: (tablo, kolon, SQL tanımı)
ADDED_COLUMNS = [
    ("room", "seats_per_row", "INTEGER NOT NULL DEFAULT 6"),
    ("reservation", "seat_number", "INTEGER"),
]


def add_missing_columns(target=None) -> list[str]:
    """Eksik kolonları ekler; eklenenleri "tablo.kolon" olarak döndürür."""
    target = target or engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    added = []
    with target.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table not in tables:
                continue
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))
                added.append(f"{table}.{column}")
    return added


def create_db_and_tables() -> None:
    from app import models  # noqa: F401  (tabloların metadata'ya kaydı için)

    SQLModel.metadata.create_all(engine)
    add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
