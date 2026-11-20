"""Veritabanı tabloları (SQLModel)."""
import secrets
from datetime import date, time
from enum import Enum

# Tüm zamanlar kampüs yerel saatinde, tz bilgisi olmadan saklanır (bkz. app/core/clock.py)
from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from app.core import clock


class Role(str, Enum):
    student = "student"
    admin = "admin"


class RoomType(str, Enum):
    study_room = "study_room"
    lab = "lab"
    hall = "hall"


class BookingMode(str, Enum):
    exclusive = "exclusive"  # oda tek rezervasyona kapatılır (grup çalışma odası)
    shared = "shared"        # koltuk bazlı: aynı anda `capacity` kadar rezervasyon (salon)


class ReservationStatus(str, Enum):
    confirmed = "confirmed"
    checked_in = "checked_in"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class ReservationSource(str, Enum):
    direct = "direct"
    waitlist = "waitlist"


class WaitlistStatus(str, Enum):
    waiting = "waiting"
    promoted = "promoted"
    cancelled = "cancelled"
    expired = "expired"


def _checkin_code() -> str:
    return secrets.token_urlsafe(16)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    hashed_password: str
    role: Role = Field(default=Role.student)
    is_active: bool = True
    penalty_points: int = 0
    banned_until: NaiveDatetime | None = None
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class Room(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    location: str = ""
    description: str = ""
    room_type: RoomType = Field(default=RoomType.study_room)
    booking_mode: BookingMode = Field(default=BookingMode.exclusive)
    capacity: int = 1
    open_time: time = time(8, 0)
    close_time: time = time(22, 0)
    slot_minutes: int = 60
    # Koltuk haritasında bir sıradaki koltuk sayısı (yalnızca shared odalarda kullanılır)
    seats_per_row: int = 6
    is_active: bool = True
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class Reservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    room_id: int = Field(foreign_key="room.id", index=True)
    start_time: NaiveDatetime = Field(index=True)
    end_time: NaiveDatetime
    # Koltuk bazlı (shared) odalarda 1..capacity; exclusive odalarda None
    seat_number: int | None = None
    status: ReservationStatus = Field(default=ReservationStatus.confirmed, index=True)
    source: ReservationSource = Field(default=ReservationSource.direct)
    checkin_code: str = Field(default_factory=_checkin_code, index=True, unique=True)
    checked_in_at: NaiveDatetime | None = None
    cancelled_at: NaiveDatetime | None = None
    cancel_reason: str | None = None
    reminder_sent: bool = False
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class WaitlistEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    room_id: int = Field(foreign_key="room.id", index=True)
    start_time: NaiveDatetime
    end_time: NaiveDatetime
    status: WaitlistStatus = Field(default=WaitlistStatus.waiting, index=True)
    promoted_reservation_id: int | None = Field(default=None, foreign_key="reservation.id")
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class PenaltyLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    reservation_id: int | None = Field(default=None, foreign_key="reservation.id")
    points: int
    reason: str
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class EmailLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    to_email: str
    subject: str
    body: str
    kind: str = Field(index=True)
    status: str = "logged"  # logged | sent | failed
    error: str | None = None
    created_at: NaiveDatetime = Field(default_factory=clock.now)


class Holiday(SQLModel, table=True):
    """Harici API'den çekilen resmi tatillerin önbelleği."""

    id: int | None = Field(default=None, primary_key=True)
    day: date = Field(index=True, unique=True)
    year: int = Field(index=True)
    name: str
