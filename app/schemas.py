"""İstek/yanıt şemaları (Pydantic)."""
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core import clock
from app.models import (
    BookingMode,
    ReservationSource,
    ReservationStatus,
    Role,
    RoomType,
    WaitlistStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth / kullanıcı ---
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=72)


class UserRead(ORMModel):
    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    penalty_points: int
    banned_until: datetime | None
    created_at: datetime


class UserAdminUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Oda ---
class RoomBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    location: str = ""
    description: str = ""
    room_type: RoomType = RoomType.study_room
    booking_mode: BookingMode = BookingMode.exclusive
    capacity: int = Field(default=1, ge=1, le=1000)
    open_time: time = time(8, 0)
    close_time: time = time(22, 0)
    slot_minutes: int = Field(default=60, ge=15, le=240)
    seats_per_row: int = Field(default=6, ge=1, le=50)


class RoomCreate(RoomBase):
    @model_validator(mode="after")
    def _hours(self):
        if self.close_time <= self.open_time:
            raise ValueError("close_time, open_time'dan sonra olmalı")
        return self


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = None
    description: str | None = None
    room_type: RoomType | None = None
    booking_mode: BookingMode | None = None
    capacity: int | None = Field(default=None, ge=1, le=1000)
    open_time: time | None = None
    close_time: time | None = None
    slot_minutes: int | None = Field(default=None, ge=15, le=240)
    seats_per_row: int | None = Field(default=None, ge=1, le=50)
    is_active: bool | None = None


class RoomRead(ORMModel, RoomBase):
    id: int
    is_active: bool


class SlotRead(BaseModel):
    start_time: datetime
    end_time: datetime
    total_seats: int
    remaining_seats: int
    available: bool
    # Müsait değilse neden: room_inactive | in_past | too_far | holiday | slot_full
    reason: str | None = None


class RoomAvailability(BaseModel):
    room: RoomRead
    remaining_seats: int


class SeatRead(BaseModel):
    number: int
    available: bool
    mine: bool = False  # isteği yapan kullanıcının bu aralıktaki koltuğu


class SeatMapRead(BaseModel):
    room_id: int
    capacity: int
    seats_per_row: int
    start_time: datetime
    end_time: datetime
    remaining_seats: int
    seats: list[SeatRead]


# --- Rezervasyon / bekleme listesi ---
class IntervalRequest(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _naive_local(cls, v: datetime) -> datetime:
        return clock.to_local_naive(v)


class ReservationCreate(IntervalRequest):
    # Yalnızca koltuk bazlı (shared) odalarda; boş bırakılırsa ilk boş koltuk atanır
    seat_number: int | None = Field(default=None, ge=1)


class WaitlistCreate(IntervalRequest):
    pass


class ReservationRead(ORMModel):
    id: int
    user_id: int
    room_id: int
    room_name: str | None = None
    start_time: datetime
    end_time: datetime
    seat_number: int | None = None
    status: ReservationStatus
    source: ReservationSource
    checkin_code: str
    checked_in_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime


class WaitlistRead(ORMModel):
    id: int
    user_id: int
    room_id: int
    start_time: datetime
    end_time: datetime
    status: WaitlistStatus
    promoted_reservation_id: int | None
    position: int | None = None
    created_at: datetime


class CheckinRequest(BaseModel):
    code: str = Field(min_length=4, max_length=200)


# --- Akıllı slot önerisi ---
class SuggestionRead(BaseModel):
    room_id: int
    room_name: str
    room_type: RoomType
    start_time: datetime
    end_time: datetime
    remaining_seats: int
    same_room: bool
    score: float                 # 0..1, yüksek = daha iyi (bkz. services/suggestions.py)
    proximity_score: float       # istenen saate yakınlık
    fit_score: float             # oda tipi / kapasite uyumu
    quiet_score: float           # 1 - geçmiş doluluk
    historical_occupancy: float  # geçmişte bu saatlerde doluluk oranı
    reasons: list[str]           # arayüzde gösterilecek kısa açıklamalar


# --- Ceza / e-posta / tatil ---
class PenaltyRead(ORMModel):
    id: int
    user_id: int
    reservation_id: int | None
    points: int
    reason: str
    created_at: datetime


class EmailLogRead(ORMModel):
    id: int
    user_id: int | None
    to_email: str
    subject: str
    body: str
    kind: str
    status: str
    error: str | None
    created_at: datetime


class HolidayRead(ORMModel):
    day: date
    name: str


# --- Analitik ---
class OccupancyCell(BaseModel):
    weekday: int | None = None       # 0 = Pazartesi
    weekday_name: str | None = None
    hour: int | None = None
    reserved_hours: float
    capacity_hours: float
    occupancy_rate: float


class RoomStats(BaseModel):
    room_id: int
    room_name: str
    total_reservations: int
    reserved_hours: float
    occupancy_rate: float
    cancelled: int
    no_show: int
    no_show_rate: float


class Summary(BaseModel):
    date_from: date
    date_to: date
    total_users: int
    total_rooms: int
    reservations_by_status: dict[str, int]
    waitlist_by_status: dict[str, int]
    reserved_hours: float
    occupancy_rate: float
    no_show_rate: float
    penalty_points_given: int
    banned_users: int
    busiest_hour: int | None
    busiest_weekday: str | None
