from sqlmodel import select

from app.core import clock
from app.core.config import settings
from app.models import EmailLog
from app.services import notifications
from tests.conftest import API, at, auth, book

TODAY = at(0, 0).date().isoformat()


def test_ics_export(client, make_user, room):
    ali = make_user("ali")
    rid = book(client, ali, room, at(1, 10), at(1, 12)).json()["id"]
    r = client.get(f"{API}/reservations/{rid}/ics", headers=auth(ali))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert f"UID:reservation-{rid}@studyspot" in text
    # 10:00 İstanbul (UTC+3) = 07:00 UTC
    assert "DTSTART:20260303T070000Z" in text and "DTEND:20260303T090000Z" in text
    assert "SUMMARY:StudySpot: Oda A" in text

    book(client, ali, room, at(2, 10), at(2, 11))
    calendar = client.get(f"{API}/reservations/me/calendar.ics", headers=auth(ali)).text
    assert calendar.count("BEGIN:VEVENT") == 2


def test_qr_png(client, make_user, room):
    ali = make_user("ali")
    rid = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    r = client.get(f"{API}/reservations/{rid}/qr", headers=auth(ali))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_occupancy_analytics(client, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    code = book(client, ali, room, at(0, 10), at(0, 12)).json()["checkin_code"]
    book(client, veli, room, at(0, 14), at(0, 15))  # gelmeyecek -> dolulukta sayılmaz
    clock.freeze(at(0, 10))
    client.post(f"{API}/checkin", json={"code": code}, headers=auth(ali))
    clock.freeze(at(0, 15))
    client.post(f"{API}/admin/jobs/run", headers=auth(admin))

    params = {"date_from": TODAY, "date_to": TODAY}
    cells = client.get(f"{API}/analytics/occupancy/heatmap", params=params, headers=auth(ali)).json()
    assert len(cells) == 14 and {c["weekday_name"] for c in cells} == {"Pazartesi"}
    rates = {c["hour"]: c["occupancy_rate"] for c in cells}
    assert rates[10] == 1.0 and rates[11] == 1.0 and rates[14] == 0.0 and rates[9] == 0.0

    hourly = client.get(f"{API}/analytics/occupancy/hourly", params=params, headers=auth(ali)).json()
    assert [h["hour"] for h in hourly if h["reserved_hours"]] == [10, 11]
    daily = client.get(f"{API}/analytics/occupancy/daily", params=params, headers=auth(ali)).json()
    assert daily == [
        {"weekday": 0, "weekday_name": "Pazartesi", "hour": None, "reserved_hours": 2.0,
         "capacity_hours": 14.0, "occupancy_rate": 0.143}
    ]

    stats = client.get(f"{API}/analytics/rooms", params=params, headers=auth(admin)).json()
    assert stats[0]["total_reservations"] == 2 and stats[0]["no_show"] == 1 and stats[0]["no_show_rate"] == 0.5

    summary = client.get(f"{API}/analytics/summary", params=params, headers=auth(admin)).json()
    assert summary["reservations_by_status"] == {"completed": 1, "no_show": 1}
    assert summary["reserved_hours"] == 2.0 and summary["occupancy_rate"] == 0.143
    assert summary["busiest_hour"] == 10 and summary["busiest_weekday"] == "Pazartesi"
    assert summary["total_users"] == 3 and summary["penalty_points_given"] == 2

    bad = {"date_from": "2026-03-10", "date_to": "2026-03-01"}
    assert client.get(f"{API}/analytics/occupancy/hourly", params=bad, headers=auth(ali)).status_code == 422


def test_deactivated_room_keeps_its_history(client, make_user, admin, room):
    ali = make_user("ali")
    code = book(client, ali, room, at(0, 10), at(0, 12)).json()["checkin_code"]
    clock.freeze(at(0, 10))
    client.post(f"{API}/checkin", json={"code": code}, headers=auth(ali))
    clock.freeze(at(0, 12))
    client.post(f"{API}/admin/jobs/run", headers=auth(admin))
    client.delete(f"{API}/rooms/{room.id}", headers=auth(admin))

    params = {"date_from": TODAY, "date_to": TODAY}
    summary = client.get(f"{API}/analytics/summary", params=params, headers=auth(admin)).json()
    assert summary["reservations_by_status"] == {"completed": 1}
    assert summary["reserved_hours"] == 2.0 and summary["occupancy_rate"] == 0.143
    assert summary["total_rooms"] == 0  # yalnızca aktif odalar sayılır
    cells = client.get(f"{API}/analytics/occupancy/heatmap", params=params, headers=auth(ali)).json()
    assert {c["hour"]: c["occupancy_rate"] for c in cells}[10] == 1.0

    # Rezervasyonu olmayan bir aralıkta pasif oda kapasiteyi şişirmez
    later = {"date_from": at(7, 0).date().isoformat(), "date_to": at(7, 0).date().isoformat()}
    assert client.get(f"{API}/analytics/occupancy/heatmap", params=later, headers=auth(ali)).json() == []


def test_smtp_backend(client, session, make_user, room, monkeypatch):
    sent = []

    class FakeSMTP:
        fail = False

        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.test", settings.SMTP_PORT)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def send_message(self, message):
            if self.fail:
                raise OSError("bağlantı koptu")
            sent.append(message)

    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    ali = make_user("ali")

    assert book(client, ali, room, at(1, 10), at(1, 11)).status_code == 201
    assert sent[0]["To"] == ali.email and "onaylandı" in sent[0]["Subject"]

    # Posta sunucusu hatası rezervasyonu engellemez, günlüğe "failed" olarak düşer
    FakeSMTP.fail = True
    assert book(client, ali, room, at(2, 10), at(2, 11)).status_code == 201
    logs = session.exec(select(EmailLog).order_by(EmailLog.id)).all()
    assert [log.status for log in logs] == ["sent", "failed"] and "bağlantı koptu" in logs[1].error


def test_csv_neutralises_spreadsheet_formulas(client, session, make_user, admin, room):
    ali = make_user("ali")
    ali.full_name = "=HYPERLINK(0)"
    session.add(ali)
    session.commit()
    book(client, ali, room, at(1, 10), at(1, 11))
    params = {"date_from": TODAY, "date_to": at(7, 0).date().isoformat()}
    r = client.get(f"{API}/admin/reports/reservations.csv", params=params, headers=auth(admin))
    assert ",'=HYPERLINK(0)," in r.text


def test_csv_report(client, make_user, admin, room):
    ali = make_user("ali")
    book(client, ali, room, at(1, 10), at(1, 11))
    params = {"date_from": TODAY, "date_to": at(7, 0).date().isoformat()}
    r = client.get(f"{API}/admin/reports/reservations.csv", params=params, headers=auth(admin))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("id,room,user_email") and len(lines) == 2
    assert "Oda A,ali@example.com" in lines[1] and "confirmed" in lines[1]
    assert client.get(f"{API}/admin/reports/reservations.csv", params=params, headers=auth(ali)).status_code == 403


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
