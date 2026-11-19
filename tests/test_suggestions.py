from datetime import timedelta

import pytest

from app.core import clock
from app.models import BookingMode, Reservation, ReservationStatus, Room, RoomType
from app.services import suggestions
from app.services.suggestions import Weights, fit_score, historical_occupancy, proximity_score
from tests.conftest import API, NOW, at, auth, book


def get_suggestions(client, user, room, start, end, **params):
    query = {"room_id": room.id, "start_time": start.isoformat(), "end_time": end.isoformat(), **params}
    return client.get(f"{API}/suggestions", params=query, headers=auth(user))


def slots(items) -> list[tuple[str, str]]:
    """Önerileri (oda adı, başlangıç saati) çiftlerine indirger."""
    return [(s["room_name"], s["start_time"][11:16]) for s in items]


def add_history(session, room, start, hours: int = 1, status=ReservationStatus.completed, user_id: int = 1):
    session.add(
        Reservation(user_id=user_id, room_id=room.id, start_time=start, end_time=start + timedelta(hours=hours),
                    status=status, created_at=start - timedelta(days=1))
    )
    session.commit()


# --- Saf skor fonksiyonları ---
def test_proximity_score():
    assert proximity_score(timedelta(0), 6) == 1.0
    assert proximity_score(timedelta(hours=-3), 6) == 0.5
    assert proximity_score(timedelta(hours=3), 6) == 0.5
    assert proximity_score(timedelta(hours=8), 6) == 0.0


def test_fit_score():
    base = Room(id=1, name="A", capacity=4, room_type=RoomType.study_room)
    assert fit_score(base, base) == 1.0
    same_type = Room(id=2, name="B", capacity=2, room_type=RoomType.study_room)
    assert fit_score(base, same_type) == 0.5 + 0.5 * 0.5
    # Farklı tip ama aynı mod (exclusive): tip uyumu yarım puan
    lab = Room(id=3, name="C", capacity=4, room_type=RoomType.lab)
    assert fit_score(base, lab) == 0.25 + 0.5
    hall = Room(id=4, name="D", capacity=8, room_type=RoomType.hall, booking_mode=BookingMode.shared)
    assert fit_score(base, hall) == 0.5 * 0.5


def test_historical_occupancy_is_time_weighted():
    rates = {(0, 10): 1.0, (0, 11): 0.0}
    assert historical_occupancy(rates, at(0, 10), at(0, 12)) == 0.5
    assert historical_occupancy(rates, at(0, 10, 30), at(0, 11, 30)) == 0.5
    assert historical_occupancy(rates, at(0, 10), at(0, 11)) == 1.0
    assert historical_occupancy({}, at(0, 10), at(0, 11)) == 0.0  # veri yok = sakin


def test_weights_are_normalised():
    assert Weights(2, 1, 1).combine(1, 0, 0) == 0.5
    assert Weights(0.5, 0.3, 0.2).combine(1, 1, 1) == pytest.approx(1.0)
    assert Weights(0, 0, 0).combine(1, 1, 1) == 0.0


# --- Aday üretimi ve kurallar ---
def test_same_room_nearest_free_slots(client, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    book(client, ali, room, at(1, 10), at(1, 11))
    book(client, ali, room, at(1, 11), at(1, 12))
    r = get_suggestions(client, veli, room, at(1, 10), at(1, 12), limit=3)
    assert r.status_code == 200
    # 2 saatlik aralık; 10-12 dolu. En yakınlar: 08-10 (2 saat önce) ve 12-14 (2 saat sonra)
    assert slots(r.json()) == [("Oda A", "08:00"), ("Oda A", "12:00"), ("Oda A", "13:00")]
    first = r.json()[0]
    assert first["same_room"] and first["end_time"].endswith("10:00:00")
    assert first["reasons"][0] == "Aynı oda, istenen saatten 2 saat önce"
    assert first["proximity_score"] == round(1 - 2 / 6, 3) and first["fit_score"] == 1.0


def test_requested_slot_itself_and_past_slots_are_excluded(client, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    book(client, ali, room, at(0, 10), at(0, 11))
    items = get_suggestions(client, veli, room, at(0, 10), at(0, 11), limit=20).json()
    starts = [s["start_time"][11:16] for s in items]
    assert "10:00" not in starts
    # NOW = 09:00; 08:00 ve 09:00 slotları geçmişte kaldı
    assert "08:00" not in starts and "09:00" not in starts
    assert starts[0] == "11:00"


def test_other_rooms_ranked_by_fit(client, make_user, make_room, room):
    ali, veli = make_user("ali"), make_user("veli")
    make_room("Oda B")  # aynı tip, aynı kapasite -> uyum 1
    make_room("Büyük Salon", room_type=RoomType.hall, booking_mode=BookingMode.shared, capacity=8)
    make_room("Kapalı Oda", is_active=False)
    book(client, ali, room, at(1, 10), at(1, 11))
    items = get_suggestions(client, veli, room, at(1, 10), at(1, 11), limit=20).json()
    assert items[0]["room_name"] == "Oda B" and items[0]["score"] == 1.0
    assert items[0]["reasons"][:2] == ["Aynı saat, farklı oda", "Aynı tipte oda (grup çalışma odası)"]
    hall = next(s for s in items if s["room_name"] == "Büyük Salon")
    assert hall["fit_score"] == 0.062 and hall["remaining_seats"] == 8
    assert "Kalan koltuk: 8" in hall["reasons"]
    # Aynı odanın 1 saat uzaklığındaki slotu, tipi uymayan salondan önde
    names = slots(items)
    assert names.index(("Oda A", "09:00")) < names.index(("Büyük Salon", "10:00"))
    assert "Kapalı Oda" not in {s["room_name"] for s in items}
    assert items == sorted(items, key=lambda s: -s["score"])


def test_suggestions_respect_user_conflict_and_seats(client, make_user, make_room, room, hall):
    ali, veli, can, deniz = (make_user(n) for n in ("ali", "veli", "can", "deniz"))
    other = make_room("Oda B")
    book(client, ali, room, at(1, 10), at(1, 11))
    book(client, veli, other, at(1, 11), at(1, 12))  # veli 11-12'de zaten Oda B'de
    book(client, can, hall, at(1, 10), at(1, 11))
    book(client, deniz, hall, at(1, 10), at(1, 11))  # salonun iki koltuğu da dolu
    items = get_suggestions(client, veli, room, at(1, 10), at(1, 11), limit=20).json()
    pairs = slots(items)
    assert ("Oda A", "11:00") not in pairs        # kullanıcının çakışması
    assert ("Salon", "10:00") not in pairs        # kalan koltuk yok
    assert ("Oda B", "10:00") in pairs and ("Oda A", "09:00") in pairs


def test_suggestions_respect_daily_limit(client, make_user, make_room, room):
    ali, veli = make_user("ali"), make_user("veli")
    other = make_room("Oda B")
    book(client, ali, room, at(1, 10), at(1, 12))
    assert book(client, veli, other, at(1, 14), at(1, 17)).status_code == 201  # 3 saat kullanıldı
    # 2 saat daha istemek günlük 4 saat limitini aşar: o gün hiçbir öneri kurala uymaz
    assert get_suggestions(client, veli, room, at(1, 10), at(1, 12)).json() == []
    # 1 saatlik istek sığar
    assert get_suggestions(client, veli, room, at(1, 10), at(1, 11)).json() != []


def test_every_suggestion_is_bookable(client, make_user, make_room, room, hall):
    ali, veli = make_user("ali"), make_user("veli")
    make_room("Oda B", slot_minutes=30)
    book(client, ali, room, at(2, 13), at(2, 15))
    items = get_suggestions(client, veli, room, at(2, 13), at(2, 15), limit=20).json()
    assert len(items) >= 5
    for s in items:
        r = client.post(
            f"{API}/reservations",
            json={"room_id": s["room_id"], "start_time": s["start_time"], "end_time": s["end_time"]},
            headers=auth(veli),
        )
        assert r.status_code == 201, (s, r.json())
        client.delete(f"{API}/reservations/{r.json()['id']}", headers=auth(veli))


def test_quiet_history_breaks_ties(client, session, make_user, make_room, room):
    ali, veli = make_user("ali"), make_user("veli")
    busy, calm = make_room("Oda B"), make_room("Oda C")
    # Son 4 pazartesinin 2'sinde Oda B 10:00'da doluydu; Oda C hep boş
    add_history(session, busy, at(-7, 10))
    add_history(session, busy, at(-14, 10))
    add_history(session, busy, at(-35, 10))  # 28 günlük pencerenin dışında: sayılmaz
    add_history(session, busy, at(-7, 12), status=ReservationStatus.cancelled)  # iptal: sayılmaz
    book(client, ali, room, at(7, 10), at(7, 11))  # gelecek pazartesi
    items = get_suggestions(client, veli, room, at(7, 10), at(7, 11)).json()
    names = [s["room_name"] for s in items]
    # Tip ve saat aynı; yalnızca geçmiş doluluk farklı -> sakin oda önde
    assert names[0] == "Oda C" and names.index("Oda C") < names.index("Oda B")
    by_name = {s["room_name"]: s for s in items}
    assert by_name["Oda B"]["historical_occupancy"] == 0.5 and by_name["Oda B"]["quiet_score"] == 0.5
    assert by_name["Oda C"]["historical_occupancy"] == 0.0
    assert "Geçmişte bu saatlerde doluluk %50" in by_name["Oda B"]["reasons"]


def test_weights_change_the_ranking(session, make_user, make_room, room, monkeypatch):
    veli = make_user("veli")
    make_room("Salon", room_type=RoomType.hall, booking_mode=BookingMode.shared, capacity=8)
    session.add(Reservation(user_id=veli.id + 1, room_id=room.id, start_time=at(1, 10), end_time=at(1, 11)))
    session.commit()
    default = suggestions.suggest(session, veli, room.id, at(1, 10), at(1, 11), NOW, limit=1)
    assert (default[0].room_name, default[0].start_time) == ("Oda A", at(1, 9))
    # Yalnızca zaman yakınlığı önemliyse aynı saatteki salon öne geçer
    only_time = suggestions.suggest(session, veli, room.id, at(1, 10), at(1, 11), NOW, 1, Weights(1, 0, 0))
    assert only_time[0].room_name == "Salon" and only_time[0].score == 1.0
    # Ayarlar .env üzerinden de değişir
    monkeypatch.setattr(suggestions.settings, "SUGGEST_WEIGHT_FIT", 0.0)
    monkeypatch.setattr(suggestions.settings, "SUGGEST_WEIGHT_QUIET", 0.0)
    assert suggestions.suggest(session, veli, room.id, at(1, 10), at(1, 11), NOW, 1)[0].room_name == "Salon"


# --- HTTP katmanı ---
def test_slot_full_response_contains_suggestions(client, make_user, make_room, room):
    ali, veli = make_user("ali"), make_user("veli")
    make_room("Oda B")
    book(client, ali, room, at(1, 10), at(1, 11))
    r = book(client, veli, room, at(1, 10), at(1, 11))
    body = r.json()
    assert r.status_code == 409 and body["code"] == "slot_full" and "Bekleme" in body["detail"]
    assert slots(body["suggestions"])[:2] == [("Oda B", "10:00"), ("Oda A", "09:00")]
    # Önerinin kendisi tek tıkla alınabilir
    s = body["suggestions"][0]
    payload = {"room_id": s["room_id"], "start_time": s["start_time"], "end_time": s["end_time"]}
    assert client.post(f"{API}/reservations", json=payload, headers=auth(veli)).status_code == 201
    # Başka hatalarda öneri alanı yok
    conflict = book(client, veli, room, at(1, 10), at(1, 11)).json()
    assert conflict["code"] == "user_conflict" and "suggestions" not in conflict


def test_suggestions_endpoint_errors(client, make_user, room):
    veli = make_user("veli")
    params = {"room_id": room.id, "start_time": at(1, 10).isoformat(), "end_time": at(1, 11).isoformat()}
    assert client.get(f"{API}/suggestions", params=params).status_code == 401
    r = get_suggestions(client, veli, room, at(1, 11), at(1, 10))
    assert r.status_code == 400 and r.json()["code"] == "invalid_interval"
    missing = Room(id=999, name="Yok")
    assert get_suggestions(client, veli, missing, at(1, 10), at(1, 11)).json()["code"] == "room_not_found"


def test_banned_user_gets_no_suggestions(client, session, make_user, room):
    veli = make_user("veli")
    veli.banned_until = NOW + timedelta(days=3)
    session.add(veli)
    session.commit()
    r = get_suggestions(client, veli, room, at(1, 10), at(1, 11))
    assert r.status_code == 403 and r.json()["code"] == "user_banned"


def test_timezone_aware_query_is_converted(client, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    book(client, ali, room, at(1, 10), at(1, 11))
    # 07:00Z = 10:00 İstanbul
    r = client.get(
        f"{API}/suggestions",
        params={"room_id": room.id, "start_time": "2026-03-03T07:00:00Z", "end_time": "2026-03-03T08:00:00Z"},
        headers=auth(veli),
    )
    assert slots(r.json())[0] == ("Oda A", "09:00")


def test_quiet_hours(client, session, make_user, room):
    veli = make_user("veli")
    for weeks in (1, 2, 3):
        add_history(session, room, at(-7 * weeks, 10), hours=2)  # pazartesi 10-12 hep dolu
    add_history(session, room, at(-6, 14))  # bir salı 14:00
    r = client.get(f"{API}/rooms/{room.id}/quiet-hours", params={"weekday": 0, "limit": 24}, headers=auth(veli))
    cells = r.json()
    assert r.status_code == 200 and len(cells) == 14  # 08-22 arası
    assert [c["hour"] for c in cells[:3]] == [8, 9, 12]
    assert [c["hour"] for c in cells[-2:]] == [10, 11] and cells[-1]["occupancy_rate"] == 0.75
    assert {c["weekday_name"] for c in cells} == {"Pazartesi"}

    tuesday = client.get(f"{API}/rooms/{room.id}/quiet-hours", params={"weekday": 1, "limit": 24},
                         headers=auth(veli)).json()
    assert tuesday[-1]["hour"] == 14 and tuesday[-1]["occupancy_rate"] == 0.25

    overall = client.get(f"{API}/rooms/{room.id}/quiet-hours", headers=auth(veli)).json()
    assert len(overall) == 5 and all(c["occupancy_rate"] == 0 for c in overall)
    assert 10 not in [c["hour"] for c in overall]

    assert client.get(f"{API}/rooms/999/quiet-hours", headers=auth(veli)).status_code == 404
    bad = client.get(f"{API}/rooms/{room.id}/quiet-hours", params={"weekday": 7}, headers=auth(veli))
    assert bad.status_code == 422


def test_today_is_not_part_of_history(client, session, make_user, room):
    veli = make_user("veli")
    clock.freeze(at(0, 18))
    add_history(session, room, at(0, 10))  # bugün: pencereye girmez
    cells = client.get(f"{API}/rooms/{room.id}/quiet-hours", params={"weekday": 0, "limit": 24},
                       headers=auth(veli)).json()
    assert all(c["occupancy_rate"] == 0 for c in cells)
