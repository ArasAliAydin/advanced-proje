from app.core.config import settings
from app.models import Reservation, ReservationStatus
from app.services.analytics import room_stats
from tests.conftest import API, at, auth, book


def _complete(session, reservation_id):
    reservation = session.get(Reservation, reservation_id)
    reservation.status = ReservationStatus.completed
    reservation.checked_in_at = at(1, 10)
    session.add(reservation)
    session.commit()


def test_feedback_requires_owned_completed_checkin(client, session, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    reservation_id = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    rating_url = f"{API}/feedback/reservations/{reservation_id}/rating"
    issue_url = f"{API}/feedback/reservations/{reservation_id}/issues"

    assert client.post(rating_url, json={"rating": 5}, headers=auth(ali)).status_code == 409
    assert client.post(issue_url, json={"description": "Priz çalışmıyor"}, headers=auth(ali)).status_code == 409

    reservation = session.get(Reservation, reservation_id)
    reservation.status = ReservationStatus.completed
    session.add(reservation)
    session.commit()
    assert client.post(rating_url, json={"rating": 5}, headers=auth(ali)).status_code == 409

    _complete(session, reservation_id)
    assert client.post(rating_url, json={"rating": 5}, headers=auth(veli)).status_code == 403
    assert client.post(issue_url, json={"description": "Priz çalışmıyor"}, headers=auth(veli)).status_code == 403


def test_room_rating_does_not_require_a_reservation_and_can_be_updated(client, make_user, room):
    ali = make_user("ali")
    endpoint = f"{API}/feedback/rooms/{room.id}/rating"

    first = client.post(endpoint, json={"rating": 5, "comment": "Sessiz"}, headers=auth(ali))
    assert first.status_code == 200 and first.json()["rating"] == 5
    updated = client.post(endpoint, json={"rating": 3}, headers=auth(ali))
    assert updated.status_code == 200 and updated.json()["rating"] == 3
    assert client.get(f"{API}/feedback/room-ratings/me", headers=auth(ali)).json() == [
        {
            "id": first.json()["id"],
            "room_id": room.id,
            "rating": 3,
            "comment": None,
            "created_at": first.json()["created_at"],
            "updated_at": updated.json()["updated_at"],
        }
    ]
    assert client.get(f"{API}/rooms", headers=auth(ali)).json()[0]["average_rating"] == 3.0


def test_rating_once_average_and_admin_issue_resolution(client, session, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    first_id = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    second_id = book(client, veli, room, at(2, 10), at(2, 11)).json()["id"]
    _complete(session, first_id)
    _complete(session, second_id)

    first_rating = client.post(
        f"{API}/feedback/reservations/{first_id}/rating",
        json={"rating": 4, "comment": "Temizdi"},
        headers=auth(ali),
    )
    assert first_rating.status_code == 201
    assert first_rating.json()["comment"] == "Temizdi"
    assert client.post(
        f"{API}/feedback/reservations/{first_id}/rating", json={"rating": 5}, headers=auth(ali)
    ).status_code == 409
    assert client.post(
        f"{API}/feedback/reservations/{second_id}/rating", json={"rating": 2}, headers=auth(veli)
    ).status_code == 201
    assert client.get(f"{API}/rooms", headers=auth(ali)).json()[0]["average_rating"] == 3.0
    assert client.get(f"{API}/feedback/me", headers=auth(ali)).json()[0]["reservation_id"] == first_id

    issue = client.post(
        f"{API}/feedback/reservations/{first_id}/issues",
        json={"description": "Projeksiyon bozuk"},
        headers=auth(ali),
    )
    assert issue.status_code == 201
    issue_id = issue.json()["id"]
    assert client.get(f"{API}/feedback/admin/issues", headers=auth(ali)).status_code == 403
    assert [item["id"] for item in client.get(f"{API}/feedback/admin/issues", headers=auth(admin)).json()] == [issue_id]

    resolved = client.patch(f"{API}/feedback/admin/issues/{issue_id}/resolve", headers=auth(admin))
    assert resolved.status_code == 200 and resolved.json()["is_resolved"] is True
    assert resolved.json()["resolved_at"] is not None
    assert client.get(f"{API}/feedback/admin/issues", headers=auth(admin)).json() == []
    assert client.get(f"{API}/feedback/admin/issues?resolved=true", headers=auth(admin)).json()[0]["id"] == issue_id


def test_feedback_validates_rating_and_issue_text(client, session, make_user, room):
    ali = make_user("ali")
    reservation_id = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    _complete(session, reservation_id)

    assert client.post(
        f"{API}/feedback/reservations/{reservation_id}/rating", json={"rating": 6}, headers=auth(ali)
    ).status_code == 422
    assert client.post(
        f"{API}/feedback/reservations/{reservation_id}/issues", json={"description": "ok"}, headers=auth(ali)
    ).status_code == 422
    assert client.post(
        f"{API}/feedback/reservations/{reservation_id}/issues", json={"description": "   "}, headers=auth(ali)
    ).status_code == 422


def test_demo_mode_is_explicitly_disabled_by_default(client, make_user, room, monkeypatch):
    ali = make_user("ali")
    monkeypatch.setattr(settings, "DEMO_MODE_ENABLED", False)
    assert client.get(f"{API}/feedback/demo-mode", headers=auth(ali)).json() == {"enabled": False}
    response = client.post(
        f"{API}/feedback/demo-reservations", json={"room_id": room.id}, headers=auth(ali)
    )
    assert response.status_code == 403


def test_demo_reservation_keeps_rating_rule_and_is_excluded_from_analytics(
    client, session, make_user, room, monkeypatch
):
    ali = make_user("ali")
    monkeypatch.setattr(settings, "DEMO_MODE_ENABLED", True)

    response = client.post(
        f"{API}/feedback/demo-reservations", json={"room_id": room.id}, headers=auth(ali)
    )
    assert response.status_code == 201
    demo = response.json()
    assert demo["is_demo"] is True
    assert demo["status"] == "completed" and demo["checked_in_at"] is not None
    assert demo["start_time"][:10] < at(0, 0).date().isoformat()

    rating = client.post(
        f"{API}/feedback/reservations/{demo['id']}/rating", json={"rating": 5}, headers=auth(ali)
    )
    assert rating.status_code == 201
    stats = room_stats(session, at(-1, 0).date(), at(-1, 0).date())
    assert stats[0].total_reservations == 0
