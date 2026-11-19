from collections.abc import Iterator
from pathlib import Path

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


def create_db_and_tables() -> None:
    from app import models  # noqa: F401  (tabloların metadata'ya kaydı için)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
