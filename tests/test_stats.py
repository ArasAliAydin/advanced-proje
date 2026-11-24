"""Kişisel istatistikler ve doluluk tahmini. NOW = 2 Mart 2026 Pazartesi 09:00."""
from datetime import date, timedelta

import pytest

from app.models import Holiday, Reservation, ReservationStatus
from tests.conftest import API, at, auth, book

S = ReservationStatus


@pytest.fixture
def add(session):
    """Geçmiş veriyi iş kurallarına takılmadan doğrudan ekler."""
    def _add(user, room, day, hour, status=S.completed, hours=1):
        r = Reservation(user_id=user.id, room_id=room.id, start_time=at(day, hour), end_time=at(day, hour + hours),
                        status=status)
        session.add(r)
        session.commit()
        return r
    return _add


def stats(client, user):
    r = client.get(f"{API}/stats/me", headers=auth(user))
    assert r.status_code == 200
    return r.json()


def forecast(client, user, room, day: date):
    return client.get(f"{API}/rooms/{room.id}/forecast", params={"day": day.isoformat()}, headers=auth(user))


# ---------------------------------------------------------------- Kişisel istatistikler
def test_stats_for_new_user(client, make_user):
    s = stats(client, make_user("ali"))
    assert s["week_start"] == "2026-03-02" and s["week_used_hours"] == 0 and s["week_remaining_hours"] == 12
    assert s["total_reservations"] == 0 and s["attendance_rate"] is None and s["no_show_rate"] is None
    assert s["favorite_room"] is None and s["favorite_hour"] is None and s["streak_weeks"] == 0
    assert s["penalty_points"] == 0 and s["penalty_threshold"] == 6 and s["banned_until"] is None
    assert len(s["weekly_history"]) == 8 and s["weekly_history"][-1]["week_start"] == "2026-03-02"
    assert s["weekly_history"][0]["week_start"] == "2026-01-12"


def test_stats_counts_and_rates(client, make_user, room, hall, add):
    ali = make_user("ali")
    add(ali, hall, -7, 14, hours=2)            # geçen Pazartesi, Salon, 2 saat
    add(ali, hall, -6, 14)                     # geçen Salı, Salon
    add(ali, room, -5, 10)                     # geçen Çarşamba, Oda A
    add(ali, room, -4, 10, S.no_show)
    add(ali, room, -3, 10, S.cancelled)
    assert book(client, ali, room, at(0, 10), at(0, 12)).status_code == 201   # bugün 2 saat
    assert book(client, ali, room, at(2, 10), at(2, 11)).status_code == 201   # Çarşamba 1 saat

    s = stats(client, ali)
    assert s["total_reservations"] == 7 and s["attended"] == 3 and s["attended_hours"] == 4
    assert s["no_show"] == 1 and s["cancelled"] == 1 and s["upcoming"] == 2
    assert s["attendance_rate"] == 0.75 and s["no_show_rate"] == 0.25
    # Bu hafta limite sayılan: bugünkü 2 + Çarşamba 1 saat
    assert s["week_used_hours"] == 3 and s["week_remaining_hours"] == 9 and s["day_used_hours"] == 2
    assert s["favorite_room"] == {"room_id": hall.id, "room_name": "Salon", "hours": 3}
    assert s["favorite_hour"] == 14 and s["favorite_weekday"] == 0 and s["favorite_weekday_name"] == "Pazartesi"
    last_week = s["weekly_history"][-2]
    # Geçen hafta: 4 katılınan saat + 1 gelinmeyen saat limite sayılır; iptal sayılmaz
    assert last_week == {"week_start": "2026-02-23", "booked_hours": 5, "attended_hours": 4}


def test_streak_counts_consecutive_weeks(client, make_user, room, add):
    ali = make_user("ali")
    for week in (1, 2, 4):                     # 1 ve 2 hafta önce katıldı, 3 hafta önce boş
        add(ali, room, -7 * week + 1, 10)
    assert stats(client, ali)["streak_weeks"] == 2
    add(ali, room, -21 + 1, 10)                # boşluk doldu
    assert stats(client, ali)["streak_weeks"] == 4
    add(ali, room, -2 * 7 + 2, 12, S.no_show)  # gelinmeyen rezervasyon seriyi uzatmaz
    assert stats(client, ali)["streak_weeks"] == 4


def test_stats_requires_login(client):
    assert client.get(f"{API}/stats/me").status_code == 401


# ---------------------------------------------------------------- Doluluk tahmini
def test_forecast_weighted_average(client, make_user, room, add):
    ali, veli = make_user("ali"), make_user("veli")
    add(ali, room, -7, 10)                     # 1 hafta önce (ağırlık 4)
    add(ali, room, -21, 10, S.no_show)         # 3 hafta önce (ağırlık 2); no_show da talep sayılır
    add(ali, room, -14, 15, S.cancelled)       # iptal sayılmaz
    assert book(client, veli, room, at(0, 14), at(0, 15)).status_code == 201  # bugün şimdiden dolu

    r = forecast(client, ali, room, at(0, 0).date())
    assert r.status_code == 200
    f = r.json()
    assert f["weeks_used"] == 4 and f["weekday"] == 0
    assert f["history_days"] == ["2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23"]
    by_hour = {h["hour"]: h for h in f["hours"]}
    assert sorted(by_hour) == list(range(8, 22))                 # oda 08-22 açık
    assert by_hour[10]["predicted"] == 0.6 and by_hour[10]["level"] == "medium"   # (4·1 + 2·1) / 10
    assert by_hour[15]["predicted"] == 0
    assert by_hour[14]["booked_now"] == 1 and by_hour[14]["expected"] == 1 and by_hour[14]["level"] == "high"
    assert by_hour[8]["past"] is True and by_hour[9]["past"] is False             # şimdi 09:00
    assert f["best_hours"] == [9, 11, 12] and f["peak_hour"] == 14


def test_forecast_shared_room_uses_seats(client, make_user, hall, add):
    ali, veli = make_user("ali"), make_user("veli")
    add(ali, hall, -7, 10)                     # 2 koltuktan 1'i
    add(veli, hall, -7, 11)
    add(ali, hall, -7, 11)                     # 11:00'de 2 koltuk da dolu
    f = forecast(client, ali, hall, at(0, 0).date()).json()
    by_hour = {h["hour"]: h for h in f["hours"]}
    assert by_hour[10]["predicted"] == 0.2 and by_hour[10]["level"] == "low"      # 4·0.5 / 10
    assert by_hour[11]["predicted"] == 0.4 and by_hour[11]["level"] == "medium"   # 4·1.0 / 10


def test_forecast_skips_holidays_and_unfinished_days(client, session, make_user, room, add):
    ali = make_user("ali")
    add(ali, room, -7, 10)
    add(ali, room, -14, 10)
    session.add(Holiday(day=at(-7, 0).date(), year=2026, name="Test Bayramı"))
    session.commit()
    f = forecast(client, ali, room, at(0, 0).date()).json()
    assert f["weeks_used"] == 3 and "2026-02-23" not in f["history_days"]
    assert {h["hour"]: h for h in f["hours"]}[10]["predicted"] == 0.5             # 3·1 / (3+2+1)

    # Gelecek Pazartesi: 1 hafta önceki gün "bugün" (henüz bitmedi), 2 hafta önceki tatil -> ikisi de sayılmaz
    f = forecast(client, ali, room, at(7, 0).date()).json()
    assert f["history_days"] == ["2026-02-09", "2026-02-16"] and f["weeks_used"] == 2


def test_forecast_without_history(client, make_user, room):
    ali = make_user("ali")
    book(client, ali, room, at(3, 13), at(3, 14))
    f = forecast(client, ali, room, at(3, 0).date()).json()
    assert f["weeks_used"] == 4  # geçmiş Perşembeler boş ama geçmişte; doluluk 0 olarak sayılır
    hours = {h["hour"]: h for h in f["hours"]}
    assert hours[13]["expected"] == 1 and hours[13]["predicted"] == 0
    assert f["best_hours"] == [8, 9, 10] and f["peak_hour"] == 13


def test_forecast_range_and_errors(client, make_user, room):
    ali = make_user("ali")
    r = forecast(client, ali, room, at(-1, 0).date())
    assert r.status_code == 400 and r.json()["code"] == "forecast_range" and r.json()["params"] == {"days": 14}
    assert forecast(client, ali, room, at(15, 0).date()).json()["code"] == "forecast_range"
    assert forecast(client, ali, room, at(14, 0).date()).status_code == 200
    assert client.get(f"{API}/rooms/999/forecast", params={"day": "2026-03-03"}, headers=auth(ali)).status_code == 404
    assert client.get(f"{API}/rooms/{room.id}/forecast", params={"day": "2026-03-03"}).status_code == 401


# ---------------------------------------------------------------- Web arayüzü
def test_stats_web_assets(client):
    page = client.get("/").text
    assert "/static/stats.js" in page and 'data-route="stats"' in page
    js = client.get("/static/stats.js")
    assert js.status_code == 200 and "async function renderStats" in js.text
