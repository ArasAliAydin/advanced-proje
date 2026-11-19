from datetime import datetime

import pytest
from sqlmodel import select

from app.core import clock
from app.core.config import settings
from app.models import EmailLog
from app.services import holidays
from app.services.scheduling import hour_buckets, overlaps, peak_concurrency, week_bounds
from tests.conftest import API, at, auth, book


# --- Algoritma birim testleri ---
def test_overlaps_is_half_open():
    assert overlaps(at(0, 10), at(0, 12), at(0, 11), at(0, 13))
    assert not overlaps(at(0, 10), at(0, 11), at(0, 11), at(0, 12))


def test_peak_concurrency_sweep_line():
    window = (at(0, 10), at(0, 14))
    assert peak_concurrency([], *window) == 0
    # Art arda gelen iki rezervasyon aynı koltuğu paylaşabilir
    assert peak_concurrency([(at(0, 10), at(0, 11)), (at(0, 11), at(0, 12))], *window) == 1
    busy = [(at(0, 10), at(0, 12)), (at(0, 11), at(0, 13)), (at(0, 11), at(0, 12)), (at(0, 13), at(0, 14))]
    assert peak_concurrency(busy, *window) == 3
    # Pencere dışındaki yoğunluk sayılmaz
    assert peak_concurrency(busy, at(0, 12), at(0, 14)) == 1


def test_hour_buckets_and_week_bounds():
    assert list(hour_buckets(at(0, 10, 30), at(0, 12))) == [(at(0, 0).date(), 10, 0.5), (at(0, 0).date(), 11, 1.0)]
    assert week_bounds(datetime(2026, 3, 5).date()) == (datetime(2026, 3, 2), datetime(2026, 3, 9))


# --- Rezervasyon ---
def test_create_reservation(client, session, make_user, room):
    ali = make_user("ali")
    r = book(client, ali, room, at(1, 10), at(1, 12))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "confirmed" and body["room_name"] == "Oda A" and body["checkin_code"]
    assert session.exec(select(EmailLog).where(EmailLog.kind == "reservation_confirmed")).one().to_email == ali.email
    mine = client.get(f"{API}/reservations/me", headers=auth(ali)).json()
    assert [m["id"] for m in mine] == [body["id"]]


def test_exclusive_room_conflict(client, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    assert book(client, ali, room, at(1, 10), at(1, 12)).status_code == 201
    for start, end in [(at(1, 11), at(1, 13)), (at(1, 9), at(1, 11)), (at(1, 10), at(1, 12)), (at(1, 11), at(1, 12))]:
        r = book(client, veli, room, start, end)
        assert r.status_code == 409 and r.json()["code"] == "slot_full"
    # Bitişik aralıklar çakışmaz
    assert book(client, veli, room, at(1, 12), at(1, 13)).status_code == 201
    assert book(client, veli, room, at(1, 9), at(1, 10)).status_code == 201


def test_shared_room_capacity(client, make_user, hall):
    u1, u2, u3, u4 = (make_user(n) for n in ("bir", "iki", "uc", "dort"))
    assert book(client, u1, hall, at(1, 10), at(1, 11)).status_code == 201
    assert book(client, u2, hall, at(1, 11), at(1, 12)).status_code == 201
    # u1 ve u2 art arda aynı koltuğu kullanır; 10-12 için hâlâ 1 koltuk boş
    assert book(client, u3, hall, at(1, 10), at(1, 12)).status_code == 201
    r = book(client, u4, hall, at(1, 10), at(1, 12))
    assert r.status_code == 409 and r.json()["code"] == "slot_full"


def test_user_cannot_double_book_across_rooms(client, make_user, room, hall):
    ali = make_user("ali")
    assert book(client, ali, room, at(1, 10), at(1, 12)).status_code == 201
    r = book(client, ali, hall, at(1, 11), at(1, 12))
    assert r.status_code == 409 and r.json()["code"] == "user_conflict"


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        (at(1, 12), at(1, 11), "invalid_interval"),
        (at(1, 21), at(2, 9), "invalid_interval"),
        (at(1, 7), at(1, 9), "outside_hours"),
        (at(1, 21), at(1, 23), "outside_hours"),
        (at(1, 10, 30), at(1, 11, 30), "slot_misaligned"),
        (at(1, 10), at(1, 11, 15), "slot_misaligned"),
        (at(1, 10), at(1, 14), "too_long"),
        (at(0, 8), at(0, 9), "in_past"),
        (at(20, 10), at(20, 11), "too_far"),
    ],
)
def test_time_rules(client, make_user, room, start, end, code):
    r = book(client, make_user("ali"), room, start, end)
    assert r.status_code == 400 and r.json()["code"] == code


def test_timezone_aware_input_is_converted(client, make_user, room):
    payload = {"room_id": room.id, "start_time": "2026-03-03T07:00:00Z", "end_time": "2026-03-03T08:00:00Z"}
    r = client.post(f"{API}/reservations", json=payload, headers=auth(make_user("ali")))
    assert r.status_code == 201 and r.json()["start_time"] == "2026-03-03T10:00:00"  # UTC+3


def test_unknown_room(client, make_user):
    payload = {"room_id": 999, "start_time": at(1, 10).isoformat(), "end_time": at(1, 11).isoformat()}
    assert client.post(f"{API}/reservations", json=payload, headers=auth(make_user("ali"))).status_code == 404


def test_daily_limit(client, make_user, admin, room, hall):
    ali = make_user("ali")
    assert book(client, ali, room, at(1, 10), at(1, 13)).status_code == 201
    r = book(client, ali, hall, at(1, 14), at(1, 16))
    assert r.status_code == 409 and r.json()["code"] == "daily_limit"
    assert book(client, ali, hall, at(1, 14), at(1, 15)).status_code == 201  # tam 4 saat
    # İptal edilen rezervasyon limitten düşer
    first = client.get(f"{API}/reservations/me", headers=auth(ali)).json()[0]
    client.delete(f"{API}/reservations/{first['id']}", headers=auth(ali))
    assert book(client, ali, hall, at(1, 16), at(1, 18)).status_code == 201
    # Admin limite tabi değil
    assert book(client, admin, room, at(2, 8), at(2, 11)).status_code == 201
    assert book(client, admin, room, at(2, 11), at(2, 14)).status_code == 201


def test_weekly_limit(client, make_user, room):
    ali = make_user("ali")
    for day in range(4):  # Pzt-Per, 4 x 3 = 12 saat
        assert book(client, ali, room, at(day, 10), at(day, 13)).status_code == 201
    r = book(client, ali, room, at(4, 10), at(4, 11))
    assert r.status_code == 409 and r.json()["code"] == "weekly_limit"
    assert book(client, ali, room, at(7, 10), at(7, 11)).status_code == 201  # sonraki hafta


def test_cancel_and_ownership(client, session, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    rid = book(client, ali, room, at(1, 10), at(1, 12)).json()["id"]
    assert client.get(f"{API}/reservations/{rid}", headers=auth(veli)).status_code == 403
    assert client.delete(f"{API}/reservations/{rid}", headers=auth(veli)).status_code == 403
    assert client.get(f"{API}/reservations/{rid}/qr", headers=auth(veli)).status_code == 403

    r = client.delete(f"{API}/reservations/{rid}", headers=auth(ali))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.delete(f"{API}/reservations/{rid}", headers=auth(ali)).status_code == 409
    assert client.get(f"{API}/auth/me", headers=auth(ali)).json()["penalty_points"] == 0
    assert book(client, veli, room, at(1, 10), at(1, 12)).status_code == 201  # slot boşaldı

    rid2 = client.get(f"{API}/reservations", headers=auth(admin), params={"status": "confirmed"}).json()[0]["id"]
    r = client.delete(f"{API}/reservations/{rid2}", headers=auth(admin), params={"reason": "Bakım"})
    assert r.json()["cancel_reason"] == "Bakım"
    mail = session.exec(select(EmailLog).where(EmailLog.kind == "reservation_cancelled")).one()
    assert mail.to_email == veli.email and "Bakım" in mail.body


def test_late_cancel_gives_penalty(client, make_user, room):
    ali = make_user("ali")
    rid = book(client, ali, room, at(0, 10), at(0, 11)).json()["id"]
    clock.freeze(at(0, 9, 45))
    assert client.delete(f"{API}/reservations/{rid}", headers=auth(ali)).status_code == 200
    assert client.get(f"{API}/auth/me", headers=auth(ali)).json()["penalty_points"] == settings.LATE_CANCEL_PENALTY_POINTS
    penalties = client.get(f"{API}/auth/me/penalties", headers=auth(ali)).json()
    assert [p["reason"] for p in penalties] == ["Geç iptal"]


def test_cannot_cancel_after_start(client, make_user, room):
    ali = make_user("ali")
    rid = book(client, ali, room, at(0, 10), at(0, 11)).json()["id"]
    clock.freeze(at(0, 10, 5))
    r = client.delete(f"{API}/reservations/{rid}", headers=auth(ali))
    assert r.status_code == 409 and r.json()["code"] == "already_started"


def test_holiday_blocks_booking(client, make_user, admin, room, monkeypatch):
    calls = []

    def fake_fetch(year, country):
        calls.append(year)
        return [{"date": at(1, 0).date().isoformat(), "localName": "Test Bayramı"}]

    monkeypatch.setattr(settings, "HOLIDAY_CHECK_ENABLED", True)
    monkeypatch.setattr(holidays, "fetch_holidays", fake_fetch)
    ali = make_user("ali")
    r = book(client, ali, room, at(1, 10), at(1, 11))
    assert r.status_code == 400 and r.json()["code"] == "holiday" and "Test Bayramı" in r.json()["detail"]
    assert book(client, ali, room, at(2, 10), at(2, 11)).status_code == 201
    assert calls == [2026]  # ikinci istek önbellekten yanıtlandı
    listed = client.get(f"{API}/admin/holidays/2026", headers=auth(admin)).json()
    assert listed == [{"day": at(1, 0).date().isoformat(), "name": "Test Bayramı"}]


def test_holiday_api_failure_is_fail_open(client, make_user, room, monkeypatch):
    def boom(year, country):
        raise RuntimeError("API erişilemez")

    monkeypatch.setattr(settings, "HOLIDAY_CHECK_ENABLED", True)
    monkeypatch.setattr(holidays, "fetch_holidays", boom)
    monkeypatch.setattr(holidays, "_last_failure", {})
    assert book(client, make_user("ali"), room, at(1, 10), at(1, 11)).status_code == 201
