import logging

from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.config import settings
from app.main import app
from app.models import EmailLog
from app.services import holidays
from tests.conftest import API, PASSWORD, at, auth, book, join_waitlist


def test_register_login_me(client):
    payload = {"email": "Ayse@Example.com", "full_name": "Ayşe Yılmaz", "password": PASSWORD}
    r = client.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 201
    assert r.json()["role"] == "student" and r.json()["email"] == "ayse@example.com"
    assert "hashed_password" not in r.json()

    assert client.post(f"{API}/auth/register", json=payload).status_code == 409

    r = client.post(f"{API}/auth/login", data={"username": "ayse@example.com", "password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["full_name"] == "Ayşe Yılmaz"


def test_login_rejects_bad_credentials(client, make_user):
    make_user("ali")
    r = client.post(f"{API}/auth/login", data={"username": "ali@example.com", "password": "yanlis-sifre"})
    assert r.status_code == 401
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer sahte"}).status_code == 401


def test_expired_token_is_rejected(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    assert client.get(f"{API}/auth/me", headers=auth(make_user("ali"))).status_code == 401


def test_startup_creates_admin_and_warns_about_default_secret(session, caplog):
    """Lifespan: tablolar + .env'deki admin hesabı; varsayılan SECRET_KEY ile uyarı."""
    with caplog.at_level(logging.WARNING, logger="studyspot"), TestClient(app) as started:
        form = {"username": settings.ADMIN_EMAIL, "password": settings.ADMIN_PASSWORD}
        token = started.post(f"{API}/auth/login", data=form).json()["access_token"]
        me = started.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["role"] == "admin"
    assert "SECRET_KEY" in caplog.text


def test_register_validates_input(client):
    r = client.post(f"{API}/auth/register", json={"email": "gecersiz", "full_name": "A B", "password": PASSWORD})
    assert r.status_code == 422
    r = client.post(f"{API}/auth/register", json={"email": "a@example.com", "full_name": "A B", "password": "kisa"})
    assert r.status_code == 422


def test_role_based_access(client, make_user, admin):
    student = make_user("ali")
    new_room = {"name": "Lab 1", "room_type": "lab", "booking_mode": "shared", "capacity": 20}
    assert client.post(f"{API}/rooms", json=new_room, headers=auth(student)).status_code == 403
    assert client.get(f"{API}/admin/users", headers=auth(student)).status_code == 403
    assert client.get(f"{API}/analytics/summary", headers=auth(student)).status_code == 403

    r = client.post(f"{API}/rooms", json=new_room, headers=auth(admin))
    assert r.status_code == 201
    assert client.post(f"{API}/rooms", json=new_room, headers=auth(admin)).status_code == 409
    assert len(client.get(f"{API}/admin/users", headers=auth(admin)).json()) == 2


def test_admin_can_promote_and_deactivate_users(client, make_user, admin):
    student = make_user("ali")
    r = client.patch(f"{API}/admin/users/{student.id}", json={"role": "admin"}, headers=auth(admin))
    assert r.json()["role"] == "admin"
    r = client.patch(f"{API}/admin/users/{student.id}", json={"is_active": False}, headers=auth(admin))
    assert r.json()["is_active"] is False
    assert client.get(f"{API}/auth/me", headers=auth(student)).status_code == 401
    assert client.patch(f"{API}/admin/users/{admin.id}", json={"role": "student"}, headers=auth(admin)).status_code == 400


def test_room_update_and_deactivate(client, make_user, admin, room):
    student = make_user("ali")
    r = client.patch(f"{API}/rooms/{room.id}", json={"capacity": 6, "location": "B Blok"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["capacity"] == 6
    bad_hours = {"open_time": "23:00:00", "close_time": "08:00:00"}
    assert client.patch(f"{API}/rooms/{room.id}", json=bad_hours, headers=auth(admin)).status_code == 422
    # null gönderilen alan değiştirilmez (önceden 500 veriyordu)
    r = client.patch(f"{API}/rooms/{room.id}", json={"capacity": None, "open_time": None}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["capacity"] == 6 and r.json()["open_time"] == "08:00:00"

    assert client.delete(f"{API}/rooms/{room.id}", headers=auth(admin)).json()["is_active"] is False
    assert client.get(f"{API}/rooms", headers=auth(student)).json() == []
    r = book(client, student, room, at(1, 10), at(1, 11))
    assert r.status_code == 400 and r.json()["code"] == "room_inactive"


def test_closing_room_cancels_upcoming_reservations(client, session, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    rid = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    assert join_waitlist(client, veli, room, at(1, 10), at(1, 11)).status_code == 201

    r = client.patch(f"{API}/rooms/{room.id}", json={"is_active": False}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["is_active"] is False

    cancelled = client.get(f"{API}/reservations/{rid}", headers=auth(ali)).json()
    assert cancelled["status"] == "cancelled" and "kapatıldı" in cancelled["cancel_reason"]
    assert client.get(f"{API}/auth/me", headers=auth(ali)).json()["penalty_points"] == 0
    mail = session.exec(select(EmailLog).where(EmailLog.kind == "reservation_cancelled")).one()
    assert mail.to_email == ali.email
    # Sıradaki kişiye kapalı odada rezervasyon açılmaz, kaydı kapatılır
    assert client.get(f"{API}/waitlist/me", headers=auth(veli)).json()[0]["status"] == "cancelled"
    assert client.get(f"{API}/reservations/me", headers=auth(veli)).json() == []

    client.patch(f"{API}/rooms/{room.id}", json={"is_active": True}, headers=auth(admin))
    assert book(client, veli, room, at(1, 10), at(1, 11)).status_code == 201


def test_availability_matches_booking_rules(client, make_user, admin, room, monkeypatch):
    """Müsait görünen her slot gerçekten rezerve edilebilir: tatil, geçmiş ve 14 gün sınırı."""
    monkeypatch.setattr(settings, "HOLIDAY_CHECK_ENABLED", True)
    monkeypatch.setattr(
        holidays, "fetch_holidays", lambda year, country: [{"date": at(1, 0).date().isoformat(), "localName": "Bayram"}]
    )
    ali = make_user("ali")

    def reasons(day_offset: int) -> list[str | None]:
        params = {"day": at(day_offset, 0).date().isoformat()}
        slots = client.get(f"{API}/rooms/{room.id}/availability", params=params, headers=auth(ali)).json()
        assert all(s["available"] == (s["reason"] is None) for s in slots)
        return [s["reason"] for s in slots]

    def free_rooms(day_offset: int) -> list:
        params = {"start_time": at(day_offset, 10).isoformat(), "end_time": at(day_offset, 11).isoformat()}
        return client.get(f"{API}/rooms/available", params=params, headers=auth(ali)).json()

    assert set(reasons(1)) == {"holiday"} and free_rooms(1) == []
    assert set(reasons(2)) == {None} and len(free_rooms(2)) == 1
    assert set(reasons(40)) == {"too_far"} and free_rooms(40) == []
    assert set(reasons(-1)) == {"in_past"}
    assert reasons(0)[:3] == ["in_past", "in_past", None]  # saat 09:00: 08 ve 09 slotları başlamış

    book(client, ali, room, at(2, 10), at(2, 11))
    assert reasons(2)[2] == "slot_full"
    client.delete(f"{API}/rooms/{room.id}", headers=auth(admin))
    assert set(reasons(2)) == {"room_inactive"}


def test_availability_slots(client, make_user, room, hall):
    ali, veli = make_user("ali"), make_user("veli")
    assert book(client, ali, room, at(1, 10), at(1, 12)).status_code == 201
    assert book(client, veli, hall, at(1, 10), at(1, 11)).status_code == 201

    slots = client.get(
        f"{API}/rooms/{room.id}/availability", params={"day": at(1, 0).date().isoformat()}, headers=auth(ali)
    ).json()
    assert len(slots) == 14  # 08:00-22:00, 60 dk'lık dilimler
    by_hour = {s["start_time"][11:13]: s for s in slots}
    assert by_hour["09"]["available"] is True
    assert by_hour["10"]["available"] is False and by_hour["11"]["remaining_seats"] == 0
    assert by_hour["12"]["available"] is True

    params = {"start_time": at(1, 10).isoformat(), "end_time": at(1, 11).isoformat()}
    free = client.get(f"{API}/rooms/available", params=params, headers=auth(ali)).json()
    assert [(f["room"]["name"], f["remaining_seats"]) for f in free] == [("Salon", 1)]
