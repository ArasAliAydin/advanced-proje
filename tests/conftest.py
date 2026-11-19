import os
from datetime import datetime, timedelta

# Ayarlar uygulama import edilmeden önce verilmeli
os.environ.update(
    ENV_FILE=".env.tests-do-not-load",
    DATABASE_URL="sqlite://",
    HOLIDAY_CHECK_ENABLED="false",
    SCHEDULER_ENABLED="false",
    EMAIL_BACKEND="console",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.database import engine, get_session  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BookingMode, Role, Room, User  # noqa: E402

API = "/api/v1"
NOW = datetime(2026, 3, 2, 9, 0)  # Pazartesi 09:00
PASSWORD = "Sifre12345"
_HASH = hash_password(PASSWORD)  # bcrypt yavaş; bir kez hesapla


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """NOW'ın gününe göre `day_offset` gün sonrası, verilen saat."""
    return datetime(NOW.year, NOW.month, NOW.day, hour, minute) + timedelta(days=day_offset)


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.freeze(NOW)
    yield
    clock.unfreeze()


@pytest.fixture
def session():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(session):
    def _make(name: str, role: Role = Role.student) -> User:
        user = User(email=f"{name}@example.com", full_name=name.title(), hashed_password=_HASH, role=role)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return _make


@pytest.fixture
def make_room(session):
    def _make(name: str = "Oda A", **kwargs) -> Room:
        room = Room(name=name, location="Kütüphane", **kwargs)
        session.add(room)
        session.commit()
        session.refresh(room)
        return room

    return _make


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


def book(client, user: User, room: Room, start: datetime, end: datetime):
    payload = {"room_id": room.id, "start_time": start.isoformat(), "end_time": end.isoformat()}
    return client.post(f"{API}/reservations", json=payload, headers=auth(user))


def join_waitlist(client, user: User, room: Room, start: datetime, end: datetime):
    payload = {"room_id": room.id, "start_time": start.isoformat(), "end_time": end.isoformat()}
    return client.post(f"{API}/waitlist", json=payload, headers=auth(user))


@pytest.fixture
def admin(make_user):
    return make_user("admin", Role.admin)


@pytest.fixture
def room(make_room):
    return make_room()


@pytest.fixture
def hall(make_room):
    return make_room("Salon", booking_mode=BookingMode.shared, capacity=2)
