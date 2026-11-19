from sqlmodel import select

from app.core import clock
from app.core.config import settings
from app.models import EmailLog
from tests.conftest import API, at, auth, book, join_waitlist


def run_jobs(client, admin) -> dict:
    r = client.post(f"{API}/admin/jobs/run", headers=auth(admin))
    assert r.status_code == 200
    return r.json()


def me(client, user) -> dict:
    return client.get(f"{API}/auth/me", headers=auth(user)).json()


def my_waitlist(client, user) -> list[dict]:
    return client.get(f"{API}/waitlist/me", headers=auth(user)).json()


# --- Bekleme listesi ---
def test_waitlist_only_for_full_slots(client, make_user, room):
    ali, veli = make_user("ali"), make_user("veli")
    r = join_waitlist(client, veli, room, at(1, 10), at(1, 11))
    assert r.status_code == 400 and r.json()["code"] == "slot_available"

    book(client, ali, room, at(1, 10), at(1, 11))
    r = join_waitlist(client, veli, room, at(1, 10), at(1, 11))
    assert r.status_code == 201 and r.json()["position"] == 1
    assert join_waitlist(client, veli, room, at(1, 10), at(1, 11)).json()["code"] == "already_waiting"
    # Slotun sahibi kendi slotu için sıraya giremez
    assert join_waitlist(client, ali, room, at(1, 10), at(1, 11)).json()["code"] == "user_conflict"


def test_cancel_promotes_waitlist_in_fifo_order(client, session, make_user, room):
    owner, b, c, d = (make_user(n) for n in ("owner", "bora", "cem", "derya"))
    rid = book(client, owner, room, at(1, 10), at(1, 12)).json()["id"]
    assert join_waitlist(client, b, room, at(1, 10), at(1, 11)).json()["position"] == 1
    assert join_waitlist(client, c, room, at(1, 10), at(1, 12)).json()["position"] == 2
    assert join_waitlist(client, d, room, at(1, 11), at(1, 12)).json()["position"] == 2

    client.delete(f"{API}/reservations/{rid}", headers=auth(owner))

    # Bora ilk sırada -> 10-11'i alır. Cem'in 10-12 isteği artık çakışır, sırada kalır.
    # Derya 11-12'yi alır: boşalan 2 saat iki kişiye dağıtıldı.
    assert my_waitlist(client, b)[0]["status"] == "promoted"
    assert my_waitlist(client, c)[0]["status"] == "waiting"
    assert my_waitlist(client, d)[0]["status"] == "promoted"
    bora_res = client.get(f"{API}/reservations/me", headers=auth(b)).json()
    assert len(bora_res) == 1 and bora_res[0]["source"] == "waitlist" and bora_res[0]["status"] == "confirmed"
    assert bora_res[0]["id"] == my_waitlist(client, b)[0]["promoted_reservation_id"]
    mails = session.exec(select(EmailLog).where(EmailLog.kind == "waitlist_promoted")).all()
    assert {m.to_email for m in mails} == {b.email, d.email}


def test_promotion_skips_ineligible_user(client, make_user, room, hall):
    owner, b, c = make_user("owner"), make_user("bora"), make_user("cem")
    rid = book(client, owner, room, at(1, 10), at(1, 11)).json()["id"]
    join_waitlist(client, b, room, at(1, 10), at(1, 11))
    join_waitlist(client, c, room, at(1, 10), at(1, 11))
    # Bora sıradayken aynı saate başka odada yer buldu -> atlanmalı
    assert book(client, b, hall, at(1, 10), at(1, 11)).status_code == 201
    client.delete(f"{API}/reservations/{rid}", headers=auth(owner))
    assert my_waitlist(client, b)[0]["status"] == "waiting"
    assert my_waitlist(client, c)[0]["status"] == "promoted"


def test_leave_waitlist(client, make_user, admin, room):
    owner, b, c = make_user("owner"), make_user("bora"), make_user("cem")
    rid = book(client, owner, room, at(1, 10), at(1, 11)).json()["id"]
    entry_id = join_waitlist(client, b, room, at(1, 10), at(1, 11)).json()["id"]
    assert client.delete(f"{API}/waitlist/{entry_id}", headers=auth(c)).status_code == 403
    assert client.delete(f"{API}/waitlist/{entry_id}", headers=auth(b)).json()["status"] == "cancelled"
    assert client.delete(f"{API}/waitlist/{entry_id}", headers=auth(b)).status_code == 409
    client.delete(f"{API}/reservations/{rid}", headers=auth(owner))
    assert client.get(f"{API}/reservations/me", headers=auth(b)).json() == []
    assert len(client.get(f"{API}/waitlist", headers=auth(admin)).json()) == 1


# --- Check-in ---
def test_checkin_window(client, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    code = book(client, ali, room, at(0, 10), at(0, 11)).json()["checkin_code"]

    def checkin(user, value=code):
        return client.post(f"{API}/checkin", json={"code": value}, headers=auth(user))

    assert checkin(ali).json()["code"] == "too_early"
    clock.freeze(at(0, 9, 55))
    assert checkin(veli).status_code == 403
    assert checkin(ali, "olmayan-kod").status_code == 404
    r = checkin(ali)
    assert r.status_code == 200 and r.json()["status"] == "checked_in" and r.json()["checked_in_at"]
    assert checkin(ali).json()["code"] == "already_checked_in"

    # Görevli (admin) başkası adına okutabilir; süre dolunca reddedilir
    code2 = book(client, veli, room, at(0, 12), at(0, 13)).json()["checkin_code"]
    clock.freeze(at(0, 12, 16))
    assert checkin(admin, code2).json()["code"] == "too_late"
    clock.freeze(at(0, 12, 15))
    assert checkin(admin, code2).status_code == 200

    clock.freeze(at(0, 13))
    assert run_jobs(client, admin)["completed"] == 2
    statuses = {r["status"] for r in client.get(f"{API}/reservations", headers=auth(admin)).json()}
    assert statuses == {"completed"}


# --- Zamanlanmış görevler ---
def test_no_show_penalty_and_waitlist_takeover(client, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    rid = book(client, ali, room, at(0, 10), at(0, 11)).json()["id"]
    join_waitlist(client, veli, room, at(0, 10), at(0, 11))

    clock.freeze(at(0, 10, 15))
    assert run_jobs(client, admin)["no_shows"] == 0  # süre henüz dolmadı
    clock.freeze(at(0, 10, 16))
    assert run_jobs(client, admin)["no_shows"] == 1
    assert run_jobs(client, admin)["no_shows"] == 0  # idempotent

    assert client.get(f"{API}/reservations/{rid}", headers=auth(ali)).json()["status"] == "no_show"
    assert me(client, ali)["penalty_points"] == settings.NO_SHOW_PENALTY_POINTS

    # Başlamış slot sıradaki kişiye geçti; check-in süresi atama anından sayılır
    taken = client.get(f"{API}/reservations/me", headers=auth(veli)).json()[0]
    assert taken["status"] == "confirmed" and taken["source"] == "waitlist"
    clock.freeze(at(0, 10, 30))
    assert run_jobs(client, admin)["no_shows"] == 0
    r = client.post(f"{API}/checkin", json={"code": taken["checkin_code"]}, headers=auth(veli))
    assert r.status_code == 200


def test_last_minute_waitlist_assignment_is_penalty_free(client, make_user, admin, room):
    """Cezasız iptal süresi kalmadan sıradan atanan kişi, iptal etse de gelmese de ceza almaz."""
    ali, veli, cem = make_user("ali"), make_user("veli"), make_user("cem")
    rid = book(client, ali, room, at(0, 10), at(0, 11)).json()["id"]
    join_waitlist(client, veli, room, at(0, 10), at(0, 11))
    join_waitlist(client, cem, room, at(0, 10), at(0, 11))

    clock.freeze(at(0, 9, 50))
    client.delete(f"{API}/reservations/{rid}", headers=auth(ali))
    assert me(client, ali)["penalty_points"] == settings.LATE_CANCEL_PENALTY_POINTS  # kendi yaptığı rezervasyon

    clock.freeze(at(0, 9, 51))
    assigned = client.get(f"{API}/reservations/me", headers=auth(veli)).json()[0]
    assert assigned["source"] == "waitlist"
    assert client.delete(f"{API}/reservations/{assigned['id']}", headers=auth(veli)).status_code == 200
    assert me(client, veli)["penalty_points"] == 0

    # Slot Cem'e geçti; gelmezse no-show olur ve slot boşalır ama puan yazılmaz
    clock.freeze(at(0, 10, 16))
    assert run_jobs(client, admin)["no_shows"] == 1
    assert client.get(f"{API}/reservations/me", headers=auth(cem)).json()[0]["status"] == "no_show"
    assert me(client, cem)["penalty_points"] == 0
    mails = client.get(f"{API}/admin/emails", headers=auth(admin), params={"kind": "no_show"}).json()
    assert "ceza puanı uygulanmadı" in mails[0]["body"]


def test_early_waitlist_assignment_keeps_penalties(client, make_user, room):
    """Atamadan sonra cezasız iptal için vakti olan kişi normal kurallara tabidir."""
    ali, veli = make_user("ali"), make_user("veli")
    rid = book(client, ali, room, at(1, 10), at(1, 11)).json()["id"]
    join_waitlist(client, veli, room, at(1, 10), at(1, 11))
    client.delete(f"{API}/reservations/{rid}", headers=auth(ali))  # bir gün önceden: Veli'ye atanır
    assigned = client.get(f"{API}/reservations/me", headers=auth(veli)).json()[0]

    clock.freeze(at(1, 9, 45))
    client.delete(f"{API}/reservations/{assigned['id']}", headers=auth(veli))
    assert me(client, veli)["penalty_points"] == settings.LATE_CANCEL_PENALTY_POINTS


def test_takeover_checkin_deadline_never_passes_slot_end(client, make_user, admin, make_room):
    """30 dk'lık slot 10:16'da devralınırsa check-in süresi 10:31 değil, slot bitişi 10:30'dur."""
    short = make_room("Kısa Oda", slot_minutes=30)
    ali, veli = make_user("ali"), make_user("veli")
    book(client, ali, short, at(0, 10), at(0, 10, 30))
    join_waitlist(client, veli, short, at(0, 10), at(0, 10, 30))

    clock.freeze(at(0, 10, 16))
    assert run_jobs(client, admin)["no_shows"] == 1  # Ali gelmedi, slot Veli'ye geçti
    clock.freeze(at(0, 10, 31))
    assert run_jobs(client, admin)["no_shows"] == 1  # Veli de gelmedi
    assert me(client, ali)["penalty_points"] == settings.NO_SHOW_PENALTY_POINTS
    assert me(client, veli)["penalty_points"] == 0


def test_ban_after_threshold_and_admin_reset(client, session, make_user, admin, room, monkeypatch):
    monkeypatch.setattr(settings, "NO_SHOW_PENALTY_POINTS", settings.PENALTY_BAN_THRESHOLD)
    ali = make_user("ali")
    book(client, ali, room, at(0, 10), at(0, 11))
    clock.freeze(at(0, 10, 20))
    run_jobs(client, admin)

    assert me(client, ali)["banned_until"] is not None and me(client, ali)["penalty_points"] == 0
    r = book(client, ali, room, at(1, 10), at(1, 11))
    assert r.status_code == 403 and r.json()["code"] == "user_banned"
    assert session.exec(select(EmailLog).where(EmailLog.kind == "ban")).one().to_email == ali.email
    assert len(client.get(f"{API}/admin/penalties", headers=auth(admin)).json()) == 1

    r = client.post(f"{API}/admin/users/{ali.id}/reset-penalty", headers=auth(admin))
    assert r.json()["banned_until"] is None
    assert book(client, ali, room, at(1, 10), at(1, 11)).status_code == 201


def test_reminder_sent_once(client, make_user, admin, room):
    ali = make_user("ali")
    book(client, ali, room, at(0, 10), at(0, 11))
    assert run_jobs(client, admin)["reminders"] == 0  # 60 dk var
    clock.freeze(at(0, 9, 35))
    assert run_jobs(client, admin)["reminders"] == 1
    assert run_jobs(client, admin)["reminders"] == 0
    mails = client.get(f"{API}/admin/emails", headers=auth(admin), params={"kind": "reminder"}).json()
    assert len(mails) == 1 and mails[0]["to_email"] == ali.email


def test_waitlist_entries_expire(client, make_user, admin, room):
    ali, veli = make_user("ali"), make_user("veli")
    code = book(client, ali, room, at(0, 10), at(0, 11)).json()["checkin_code"]
    join_waitlist(client, veli, room, at(0, 10), at(0, 11))
    clock.freeze(at(0, 10))
    client.post(f"{API}/checkin", json={"code": code}, headers=auth(ali))
    clock.freeze(at(0, 11))
    result = run_jobs(client, admin)
    assert result["waitlist_expired"] == 1 and result["completed"] == 1
    assert my_waitlist(client, veli)[0]["status"] == "expired"
