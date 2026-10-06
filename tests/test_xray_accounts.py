"""Davetli üyeler: e-postaya bağlı hesap ve haklar, e-posta koduyla giriş, cihaz anahtarları, kota, geri bildirim,
yönetim sayfası. İlan içeriği saklanmaz; anahtar/kod/oturum yalnız özetle tutulur."""
import re
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, api, mailer, security, xray_app, yonetim
from tests.helpers import DownLLM, FakeLLM
from tests.test_xray_api import EXT, H, payload

runner = CliRunner()
ADMIN = "yonetici@cybergene.co"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "otoxray@cybergene.co")
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}))
    return sent


@pytest.fixture
def client(monkeypatch, outbox):
    monkeypatch.setattr(settings, "extension_token", EXT)
    monkeypatch.setattr(settings, "admin_emails", [ADMIN])
    monkeypatch.setattr(settings, "admin_cookie_secure", False)
    security._fails.clear()
    api._calls.clear()
    api._code_ips.clear()
    yonetim._ips.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        yield c
    xray_app.app.dependency_overrides.clear()


def member(email="uye@ornek.com", **kw):
    mid = accounts.create_member(email, **kw)
    return mid, {"Authorization": f"Bearer {accounts.issue_key(mid)}"}


def last_code(outbox, to):
    return re.search(r"\b(\d{6})\b", next(m for m in reversed(outbox) if m["to"] == to)["subject"]).group(1)


# ------------------------------------------------------------------ depo
def test_only_hashes_are_stored():
    mid = accounts.create_member("Ali@Ornek.com ")
    key = accounts.issue_key(mid, "Chrome")
    code = accounts.create_code("ali@ornek.com", "uye")
    db = sqlite3.connect(settings.xray_accounts_db)
    dump = "\n".join(str(r) for t in ("members", "member_keys", "login_codes") for r in db.execute(f"SELECT * FROM {t}"))
    assert key not in dump and accounts.hash_key(key) in dump and code not in dump
    assert accounts.get_member(mid)["email"] == "ali@ornek.com"          # normalize edildi


def test_duplicate_and_invalid_emails_rejected():
    accounts.create_member("a@b.co")
    with pytest.raises(ValueError):
        accounts.create_member("A@B.co")
    for bad in ("", "x", "a@b", "a b@c.de"):
        with pytest.raises(ValueError):
            accounts.create_member(bad)


# ------------------------------------------------------------------ haklar
def test_member_key_works_and_reports_rights(client):
    _, h = member(gunluk_kota=5, aylik_kota=50, bitis="2099-12-31")
    k = client.get("/api/v1/ping", headers=h).json()
    assert k["kullanici"] == "uye@ornek.com"
    assert k["kota"]["limit"] == 5 and k["kota"]["aylik"] == {"limit": 50, "kullanilan": 0} and k["kota"]["bitis"] == "2099-12-31"


def test_paused_expired_and_revoked_members(client):
    mid, h = member()
    accounts.set_status(mid, "durduruldu")
    r = client.get("/api/v1/ping", headers=h)
    assert r.status_code == 403 and "durduruldu" in r.json()["detail"]
    accounts.set_status(mid, "aktif")
    assert client.get("/api/v1/ping", headers=h).status_code == 200
    accounts.update_member(mid, bitis=(date.today() - timedelta(days=2)).isoformat())
    r = client.get("/api/v1/ping", headers=h)
    assert r.status_code == 403 and "doldu" in r.json()["detail"]
    accounts.update_member(mid, bitis=None)
    accounts.set_status(mid, "iptal")                    # iptal: anahtar artık hiç tanınmaz
    assert client.get("/api/v1/ping", headers=h).status_code == 401


def test_daily_and_monthly_quota(client):
    _, h = member(gunluk_kota=2)
    for _ in range(2):
        assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 200
    r = client.post("/api/v1/analyze", json=payload(), headers=h)
    assert r.status_code == 429 and "Günlük" in r.json()["detail"]
    _, h2 = member("ay@ornek.com", gunluk_kota=10, aylik_kota=1)
    assert client.post("/api/v1/analyze", json=payload(), headers=h2).status_code == 200
    r = client.post("/api/v1/analyze", json=payload(), headers=h2)
    assert r.status_code == 429 and "ay" in r.json()["detail"]


def test_failed_llm_refunds_the_quota(client):
    mid, h = member(gunluk_kota=1)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: DownLLM()
    assert client.post("/api/v1/analyze", json=payload(), headers=h).json()["beklemede"] is True
    assert accounts.used_today(mid) == 0


def test_badges_can_be_turned_off_per_member(client):
    _, h = member(rozet=False)
    body = {"items": [dict(ilan_no="A", fiyat=800_000, yil=2022, km=60000)]}
    r = client.post("/api/v1/batch-evaluate", json=body, headers=h)
    assert r.status_code == 403 and "rozet" in r.json()["detail"]
    assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 200


def test_batch_and_quick_are_limited_against_bulk_copying(client, monkeypatch):
    monkeypatch.setattr(settings, "user_daily_batch", 1)
    _, h = member()
    body = {"items": [dict(ilan_no="A", fiyat=800_000, yil=2022, km=60000)]}
    assert client.post("/api/v1/batch-evaluate", json=body, headers=h).status_code == 200
    assert client.post("/api/v1/batch-evaluate", json=body, headers=h).status_code == 429
    assert client.post("/api/v1/quick", json=payload(), headers=h).status_code == 200
    assert client.post("/api/v1/quick", json=payload(), headers=h).status_code == 429
    assert client.post("/api/v1/batch-evaluate", json=body, headers=H).status_code == 200   # sahip kotasız


def test_rule_weights_trace_only_for_owner(client):
    _, h = member()
    assert client.post("/api/v1/analyze", json=payload(), headers=h).json()["trace"] == []
    assert client.post("/api/v1/analyze", json=payload(), headers=H).json()["trace"]


def test_owner_never_touches_the_accounts_db(client):
    import pathlib
    client.post("/api/v1/analyze", json=payload(), headers=H)
    client.post("/api/v1/feedback", json={"ilan_no": "1001", "oy": "pos"}, headers=H)
    assert not pathlib.Path(settings.xray_accounts_db).exists()


# ------------------------------------------------------------------ e-posta koduyla giriş
def test_email_code_login_issues_a_device_key(client, outbox):
    member("davetli@ornek.com", gunluk_kota=7)
    r = client.post("/api/v1/auth/kod", json={"email": " Davetli@Ornek.com"})
    assert r.status_code == 200 and len(outbox) == 1 and outbox[0]["to"] == "davetli@ornek.com"
    code = last_code(outbox, "davetli@ornek.com")
    r = client.post("/api/v1/auth/giris", json={"email": "davetli@ornek.com", "kod": code, "cihaz": "Chrome"})
    assert r.status_code == 200
    d = r.json()
    assert d["anahtar"].startswith("oxr_") and d["kota"]["limit"] == 7
    h = {"Authorization": f"Bearer {d['anahtar']}"}
    assert client.get("/api/v1/ping", headers=h).status_code == 200
    assert client.post("/api/v1/auth/giris", json={"email": "davetli@ornek.com", "kod": code}).status_code == 401  # tek kullanımlık
    assert client.post("/api/v1/cikis", headers=h).status_code == 200                       # bu cihazdan çıkış
    assert client.get("/api/v1/ping", headers=h).status_code == 401


def test_code_request_does_not_reveal_membership(client, outbox):
    member("var@ornek.com")
    a = client.post("/api/v1/auth/kod", json={"email": "var@ornek.com"})
    b = client.post("/api/v1/auth/kod", json={"email": "yok@ornek.com"})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert [m["to"] for m in outbox] == ["var@ornek.com"]


def test_paused_member_gets_no_code(client, outbox):
    mid, _ = member("dur@ornek.com")
    accounts.set_status(mid, "durduruldu")
    assert client.post("/api/v1/auth/kod", json={"email": "dur@ornek.com"}).status_code == 200
    assert outbox == []


def test_code_rate_limit_attempt_limit_and_expiry(client, outbox, monkeypatch):
    member("x@ornek.com")
    client.post("/api/v1/auth/kod", json={"email": "x@ornek.com"})
    client.post("/api/v1/auth/kod", json={"email": "x@ornek.com"})           # 60 sn dolmadan ikinci kod üretilmez
    assert len(outbox) == 1
    code = last_code(outbox, "x@ornek.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(accounts.CODE_MAX_ATTEMPTS):
        assert client.post("/api/v1/auth/giris", json={"email": "x@ornek.com", "kod": wrong}).status_code == 401
    security._fails.clear()
    assert client.post("/api/v1/auth/giris", json={"email": "x@ornek.com", "kod": code}).status_code == 401  # kilitlendi


def test_code_expires(client, outbox, monkeypatch):
    member("s@ornek.com")
    client.post("/api/v1/auth/kod", json={"email": "s@ornek.com"})
    code = last_code(outbox, "s@ornek.com")
    import time as _t
    real = _t.time
    monkeypatch.setattr(accounts.time, "time", lambda: real() + accounts.CODE_TTL_S + 1)
    assert client.post("/api/v1/auth/giris", json={"email": "s@ornek.com", "kod": code}).status_code == 401


def test_no_smtp_is_an_honest_error(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    member("n@ornek.com")
    assert client.post("/api/v1/auth/kod", json={"email": "n@ornek.com"}).status_code == 503


def test_auth_input_validation(client):
    assert client.post("/api/v1/auth/kod", json={"email": "gecersiz"}).status_code == 422
    assert client.post("/api/v1/auth/giris", json={"email": "a@b.co", "kod": "12ab56"}).status_code == 422


# ------------------------------------------------------------------ geri bildirim
def test_feedback_stored_without_listing_content_and_phone_masked(client):
    mid, h = member()
    r = client.post("/api/v1/feedback", headers=h, json={
        "ilan_no": "1001", "etiket": "ALINIR", "skor": 8.1, "oy": "neg", "sonuc": "ekspertiz_agir_kusur",
        "notu": "Ekspertizde şase işlemli çıktı, satıcı 0532 123 45 67"})
    assert r.status_code == 200 and r.json()["kaydedildi"] is True
    fb = accounts.list_feedback()[0]
    assert fb["member_id"] == mid and fb["email"] == "uye@ornek.com" and "0532" not in fb["notu"]
    cols = {d[1] for d in sqlite3.connect(settings.xray_accounts_db).execute("PRAGMA table_info(feedback)")}
    assert not cols & {"aciklama", "baslik", "fiyat", "url", "parts"}


@pytest.mark.parametrize("body", [
    {"ilan_no": "1001"}, {"ilan_no": "1001", "oy": "belki"}, {"ilan_no": "1001", "sonuc": "uydurma"},
    {"ilan_no": "x" * 30, "oy": "pos"}, {"ilan_no": "1001", "notu": "a" * 501},
])
def test_feedback_validation(client, body):
    _, h = member()
    assert client.post("/api/v1/feedback", json=body, headers=h).status_code == 422


def test_feedback_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_daily_limit", 1)
    _, h = member()
    assert client.post("/api/v1/feedback", json={"ilan_no": "1", "oy": "pos"}, headers=h).status_code == 200
    assert client.post("/api/v1/feedback", json={"ilan_no": "2", "oy": "pos"}, headers=h).status_code == 429


# ------------------------------------------------------------------ yönetim sayfası
def admin_login(client, outbox):
    client.post("/yonetim/giris", data={"email": ADMIN})
    code = last_code(outbox, ADMIN)
    r = client.post("/yonetim/dogrula", data={"email": ADMIN, "kod": code}, follow_redirects=False)
    assert r.status_code == 303 and "oxr_yonetim" in r.cookies
    page = client.get("/yonetim").text
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def test_admin_requires_login_and_only_admin_emails_get_codes(client, outbox):
    r = client.get("/yonetim", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/yonetim/giris")
    client.post("/yonetim/giris", data={"email": "baskasi@ornek.com"})
    assert outbox == []                                      # listede olmayana kod gitmez (ekran aynı)
    r = client.post("/yonetim/dogrula", data={"email": "baskasi@ornek.com", "kod": "123456"}, follow_redirects=False)
    assert "kod_hatali" in r.headers["location"]


def test_admin_adds_member_with_rights_and_invite(client, outbox):
    csrf = admin_login(client, outbox)
    r = client.post("/yonetim/uye", data={"csrf": csrf, "email": "yeni@ornek.com", "ad": "Yeni", "gunluk": "12",
                                          "aylik": "100", "bitis": "2099-01-31", "rozet": "on", "davet": "on"},
                    follow_redirects=False)
    assert "eklendi_davet" in r.headers["location"]
    m = accounts.get_member_by_email("yeni@ornek.com")
    assert (m["gunluk_kota"], m["aylik_kota"], m["bitis"], m["rozet"]) == (12, 100, "2099-01-31", 1)
    invite = next(x for x in outbox if x["to"] == "yeni@ornek.com")
    assert "günde 12 analiz" in invite["body"] and "2099-01-31" in invite["body"]
    assert "yeni@ornek.com" in client.get("/yonetim").text


def test_admin_edits_pauses_and_logs_out_member(client, outbox):
    csrf = admin_login(client, outbox)
    mid, h = member("d@ornek.com")
    client.post(f"/yonetim/uye/{mid}", data={"csrf": csrf, "gunluk": "3", "aylik": "", "bitis": "", "ad": "", "notu": ""})
    m = accounts.get_member(mid)
    assert m["gunluk_kota"] == 3 and m["rozet"] == 0          # işaretsiz kutu = kapalı
    client.post(f"/yonetim/uye/{mid}/durum", data={"csrf": csrf, "durum": "durduruldu"})
    assert client.get("/api/v1/ping", headers=h).status_code == 403
    client.post(f"/yonetim/uye/{mid}/durum", data={"csrf": csrf, "durum": "aktif"})
    client.post(f"/yonetim/uye/{mid}/cihazlar", data={"csrf": csrf})
    assert client.get("/api/v1/ping", headers=h).status_code == 401
    assert "d@ornek.com" in client.get(f"/yonetim/uye/{mid}").text


def test_admin_csrf_and_origin_enforced(client, outbox):
    csrf = admin_login(client, outbox)
    r = client.post("/yonetim/uye", data={"csrf": "yanlis", "email": "z@ornek.com", "gunluk": "5"}, follow_redirects=False)
    assert r.headers["location"].endswith("/yonetim/giris") and not accounts.get_member_by_email("z@ornek.com")
    r = client.post("/yonetim/uye", data={"csrf": csrf, "email": "z@ornek.com", "gunluk": "5"},
                    headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert not accounts.get_member_by_email("z@ornek.com")


def test_admin_pages_escape_user_input(client, outbox):
    csrf = admin_login(client, outbox)
    mid = accounts.create_member("x@ornek.com", ad="<script>alert(1)</script>")
    accounts.add_feedback(mid, "1", None, None, "pos", None, "<img src=x onerror=alert(1)>")
    for page in (client.get(f"/yonetim/uye/{mid}").text, client.get("/yonetim/geri-bildirim").text):
        assert "<script>alert" not in page and "<img src=x" not in page


def test_admin_logout(client, outbox):
    csrf = admin_login(client, outbox)
    client.post("/yonetim/cikis", data={"csrf": csrf})
    assert client.get("/yonetim", follow_redirects=False).status_code == 303


# ------------------------------------------------------------------ CLI
def test_cli_member_lifecycle():
    r = runner.invoke(cli.app, ["xray", "user", "add", "ayse@ornek.com", "--ad", "Ayşe", "--gunluk", "5",
                                "--bitis", "2099-12-31"])
    assert r.exit_code == 0, r.output
    m = accounts.get_member_by_email("ayse@ornek.com")
    assert m["gunluk_kota"] == 5 and m["bitis"] == "2099-12-31"
    assert "ayse@ornek.com" in runner.invoke(cli.app, ["xray", "user", "list"]).output
    assert runner.invoke(cli.app, ["xray", "user", "set", "ayse@ornek.com", "--aylik", "40", "--rozetsiz"]).exit_code == 0
    m = accounts.get_member(m["id"])
    assert m["aylik_kota"] == 40 and m["rozet"] == 0
    assert runner.invoke(cli.app, ["xray", "user", "pause", str(m["id"])]).exit_code == 0
    assert accounts.get_member(m["id"])["durum"] == "durduruldu"
    assert runner.invoke(cli.app, ["xray", "user", "revoke", "ayse@ornek.com"]).exit_code == 0
    assert runner.invoke(cli.app, ["xray", "user", "revoke", "ayse@ornek.com"]).exit_code == 3
    assert runner.invoke(cli.app, ["xray", "user", "add", "gecersiz"]).exit_code == 3


def test_cli_feedback_list_json():
    mid = accounts.create_member("veli@ornek.com")
    accounts.add_feedback(mid, "42", "DUSUNULEBILIR", 6.0, "pos", None, "iyi")
    r = runner.invoke(cli.app, ["xray", "feedback", "--json"])
    assert r.exit_code == 0 and '"ilan_no": "42"' in r.stdout
