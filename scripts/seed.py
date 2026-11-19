"""Demo verisi üretir: odalar, öğrenciler, önceki 3 haftanın rezervasyon geçmişi ve birkaç yaklaşan rezervasyon.

Kullanım:  python -m scripts.seed          (veritabanı boşsa doldurur)
           python -m scripts.seed --reset  (tüm tabloları silip yeniden oluşturur)
"""
import random
import sys
from datetime import datetime, time, timedelta

from sqlmodel import Session, SQLModel, select

from app.core import clock
from app.core.database import create_db_and_tables, engine
from app.core.security import hash_password
from app.main import ensure_admin
from app.models import BookingMode, Reservation, ReservationStatus, Role, Room, RoomType, User
from app.services import reservation_service as rs

STUDENT_PASSWORD = "Student123!"  # yalnızca demo hesapları için

ROOMS = [
    dict(name="Grup Odası 1", location="Kütüphane 2. Kat", capacity=6, description="Akıllı tahta, 6 kişilik"),
    dict(name="Grup Odası 2", location="Kütüphane 2. Kat", capacity=4, slot_minutes=30),
    dict(name="Sessiz Çalışma Salonu", location="Kütüphane Zemin Kat", capacity=8, room_type=RoomType.hall,
         booking_mode=BookingMode.shared, close_time=time(23, 0)),
    dict(name="Bilgisayar Lab A", location="Mühendislik B-104", capacity=5, room_type=RoomType.lab,
         booking_mode=BookingMode.shared, open_time=time(9, 0), close_time=time(18, 0)),
]
STUDENTS = ["Ayşe Yılmaz", "Mehmet Demir", "Zeynep Kaya", "Can Öztürk", "Elif Şahin", "Burak Çelik"]


def seed() -> None:
    random.seed(42)
    now = clock.now()
    with Session(engine) as session:
        if session.exec(select(Room)).first():
            print("Veritabanında zaten veri var. Sıfırlamak için: python -m scripts.seed --reset")
            return
        rooms = [Room(**data) for data in ROOMS]
        hashed = hash_password(STUDENT_PASSWORD)
        students = [
            User(email=f"ogrenci{i}@example.com", full_name=name, hashed_password=hashed, role=Role.student)
            for i, name in enumerate(STUDENTS, start=1)
        ]
        session.add_all(rooms + students)
        session.commit()

        # Geçmiş: analitik endpoint'lerinin anlamlı veri döndürmesi için (öğlen saatleri daha yoğun).
        # Yalnızca önceki 3 tam haftaya yazılır: bu haftaya yazılsaydı öğrenciler haftalık limite
        # takılır ve demoda yeni rezervasyon yapamazdı.
        past = 0
        this_monday = now.date() - timedelta(days=now.weekday())
        for days_before in range(21, 0, -1):
            day = this_monday - timedelta(days=days_before)
            weekend = day.weekday() >= 5
            for room in rooms:
                seats = rs.seats_limit(room)
                for hour in range(room.open_time.hour, room.close_time.hour):
                    peak = 0.75 if 11 <= hour <= 16 else 0.35
                    for _ in range(seats):
                        if random.random() > peak * (0.4 if weekend else 1):
                            continue
                        start = datetime.combine(day, time(hour))
                        status = random.choices(
                            [ReservationStatus.completed, ReservationStatus.no_show, ReservationStatus.cancelled],
                            weights=[82, 10, 8],
                        )[0]
                        session.add(
                            Reservation(
                                user_id=random.choice(students).id, room_id=room.id, start_time=start,
                                end_time=start + timedelta(hours=1), status=status,
                                checked_in_at=start if status == ReservationStatus.completed else None,
                                created_at=start - timedelta(days=1),
                            )
                        )
                        past += 1
        session.commit()

        # Gelecek: gerçek iş kurallarından geçirilerek oluşturulur
        upcoming = 0
        for day_offset in range(1, 4):
            for student in students:
                room = random.choice(rooms)
                start = datetime.combine((now + timedelta(days=day_offset)).date(), time(random.randint(10, 15)))
                try:
                    rs.create_reservation(session, student, room, start, start + timedelta(hours=1), now)
                    upcoming += 1
                except rs.BookingError:
                    pass
        session.commit()
    print(f"{len(ROOMS)} oda, {len(STUDENTS)} öğrenci, {past} geçmiş ve {upcoming} yaklaşan rezervasyon oluşturuldu.")
    print("Öğrenci hesapları: ogrenci1@example.com ... ogrenci6@example.com (şifre scripts/seed.py içinde)")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        from app import models  # noqa: F401

        SQLModel.metadata.drop_all(engine)
    create_db_and_tables()
    ensure_admin()
    seed()
