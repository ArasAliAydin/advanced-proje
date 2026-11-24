"""v3: koltuk haritası (shared odalarda koltuk seçimi) ve hata parametreleri."""
from sqlalchemy import create_engine, inspect, text

from app.core.database import add_missing_columns
from tests.conftest import API, at, auth, book, join_waitlist


def book_seat(client, user, room, start, end, seat):
    payload = {"room_id": room.id, "start_time": start.isoformat(), "end_time": end.isoformat(), "seat_number": seat}
    return client.post(f"{API}/reservations", json=payload, headers=auth(user))


def seat_map(client, user, room, start, end):
    params = {"start_time": start.isoformat(), "end_time": end.isoformat()}
    return client.get(f"{API}/rooms/{room.id}/seats", params=params, headers=auth(user))


def test_shared_room_assigns_first_free_seat(client, make_user, hall):
    ali, ayse = make_user("ali"), make_user("ayse")
    first = book(client, ali, hall, at(1, 10), at(1, 11)).json()
    second = book(client, ayse, hall, at(1, 10), at(1, 11)).json()
    assert (first["seat_number"], second["seat_number"]) == (1, 2)


def test_user_can_pick_seat_and_taken_seat_is_rejected(client, make_user, make_room):
    salon = make_room("Büyük Salon", booking_mode="shared", capacity=10, seats_per_row=5)
    ali, ayse = make_user("ali"), make_user("ayse")
    r = book_seat(client, ali, salon, at(1, 10), at(1, 12), 7)
    assert r.status_code == 201 and r.json()["seat_number"] == 7

    # 11-12 aralığı ali'nin 10-12 rezervasyonuyla kesişir: 7 numara dolu
    r = book_seat(client, ayse, salon, at(1, 11), at(1, 12), 7)
    assert r.status_code == 409 and r.json()["code"] == "seat_taken" and r.json()["params"] == {"seat": 7}
    assert book_seat(client, ayse, salon, at(1, 12), at(1, 13), 7).status_code == 201  # art arda kullanılabilir

    r = book_seat(client, ayse, salon, at(1, 14), at(1, 15), 11)
    assert r.status_code == 400 and r.json()["code"] == "invalid_seat" and r.json()["params"] == {"max": 10}


def test_seat_map_shows_taken_and_own_seats(client, make_user, make_room):
    salon = make_room("Büyük Salon", booking_mode="shared", capacity=6, seats_per_row=3)
    ali, ayse = make_user("ali"), make_user("ayse")
    book_seat(client, ali, salon, at(1, 10), at(1, 11), 2)
    book_seat(client, ayse, salon, at(1, 10), at(1, 12), 5)

    data = seat_map(client, ali, salon, at(1, 10), at(1, 11)).json()
    assert (data["capacity"], data["seats_per_row"], data["remaining_seats"]) == (6, 3, 4)
    by_number = {s["number"]: s for s in data["seats"]}
    assert [n for n, s in by_number.items() if not s["available"]] == [2, 5]
    assert by_number[2]["mine"] and not by_number[5]["mine"]

    # 11-12: yalnızca ayşe'nin koltuğu dolu
    later = seat_map(client, ali, salon, at(1, 11), at(1, 12)).json()
    assert [s["number"] for s in later["seats"] if not s["available"]] == [5]


def test_multi_slot_interval_needs_one_seat_for_whole_time(client, make_user, hall):
    """10-11'de 1, 11-12'de 2 numara doluysa 10-12 için kesintisiz boş koltuk yoktur."""
    ali, ayse, can = make_user("ali"), make_user("ayse"), make_user("can")
    assert book_seat(client, ali, hall, at(1, 10), at(1, 11), 1).status_code == 201
    assert book_seat(client, ayse, hall, at(1, 11), at(1, 12), 2).status_code == 201
    assert seat_map(client, can, hall, at(1, 10), at(1, 12)).json()["remaining_seats"] == 0
    r = book(client, can, hall, at(1, 10), at(1, 12))
    assert r.status_code == 409 and r.json()["code"] == "slot_full"
    # Tek tek slotlarda yer var
    assert book(client, can, hall, at(1, 10), at(1, 11)).json()["seat_number"] == 2


def test_exclusive_room_has_no_seats(client, make_user, room):
    ali = make_user("ali")
    r = book_seat(client, ali, room, at(1, 10), at(1, 11), 1)
    assert r.status_code == 400 and r.json()["code"] == "seat_not_applicable"
    assert seat_map(client, ali, room, at(1, 10), at(1, 11)).json()["code"] == "seat_not_applicable"
    assert book(client, ali, room, at(1, 10), at(1, 11)).json()["seat_number"] is None


def test_waitlist_promotion_assigns_freed_seat(client, make_user, hall):
    ali, ayse, can = make_user("ali"), make_user("ayse"), make_user("can")
    book(client, ali, hall, at(1, 10), at(1, 11))
    second = book(client, ayse, hall, at(1, 10), at(1, 11)).json()
    assert join_waitlist(client, can, hall, at(1, 10), at(1, 11)).status_code == 201
    client.delete(f"{API}/reservations/{second['id']}", headers=auth(ayse))
    mine = client.get(f"{API}/reservations/me", headers=auth(can)).json()
    assert [(r["source"], r["seat_number"]) for r in mine] == [("waitlist", 2)]


def test_room_seats_per_row_validation(client, admin):
    payload = {"name": "Salon X", "booking_mode": "shared", "capacity": 30, "seats_per_row": 0}
    assert client.post(f"{API}/rooms", json=payload, headers=auth(admin)).status_code == 422
    payload["seats_per_row"] = 10
    created = client.post(f"{API}/rooms", json=payload, headers=auth(admin)).json()
    assert created["seats_per_row"] == 10
    r = client.patch(f"{API}/rooms/{created['id']}", json={"seats_per_row": 6}, headers=auth(admin))
    assert r.json()["seats_per_row"] == 6


def test_csv_export_includes_seat(client, make_user, admin, hall):
    ali = make_user("ali")
    book_seat(client, ali, hall, at(1, 10), at(1, 11), 2)
    params = {"date_from": at(0, 0).date().isoformat(), "date_to": at(2, 0).date().isoformat()}
    lines = client.get(f"{API}/admin/reports/reservations.csv", params=params, headers=auth(admin)).text.splitlines()
    assert lines[0].endswith(",seat") and lines[1].endswith(",2")


def test_business_errors_carry_params_for_translation(client, make_user, room):
    ali = make_user("ali")
    r = book(client, ali, room, at(1, 6), at(1, 7))
    assert r.json()["code"] == "outside_hours" and r.json()["params"] == {"open": "08:00", "close": "22:00"}
    r = book(client, ali, room, at(1, 10), at(1, 14))
    assert r.json()["code"] == "too_long" and r.json()["params"] == {"hours": 3}


def test_missing_columns_are_added_to_old_database(tmp_path):
    """v2'den kalan SQLite dosyasında yeni kolonlar yoksa açılışta eklenir."""
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE room (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("CREATE TABLE reservation (id INTEGER PRIMARY KEY, room_id INTEGER)"))
        conn.execute(text("INSERT INTO room (id, name) VALUES (1, 'Eski oda')"))
        conn.execute(text("INSERT INTO reservation (id, room_id) VALUES (1, 1)"))
    assert sorted(add_missing_columns(old)) == [
        "reservation.is_demo", "reservation.seat_number", "room.seats_per_row",
    ]
    assert add_missing_columns(old) == []  # ikinci çalıştırmada değişiklik yok
    columns = {c["name"] for c in inspect(old).get_columns("room")}
    assert "seats_per_row" in columns
    with old.connect() as conn:
        assert conn.execute(text("SELECT seats_per_row FROM room")).scalar() == 6
        assert conn.execute(text("SELECT is_demo FROM reservation")).scalar() == 0
    old.dispose()
