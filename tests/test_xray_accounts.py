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
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, html=None: sent.append({"to": to, "subject": subject, "body": body, "html": html}))
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
    for i in range(2):
        assert client.post("/api/v1/analyze", json=payload(ilan_no=f"D{i}"), headers=h).status_code == 200
    r = client.post("/api/v1/analyze", json=payload(ilan_no="D9"), headers=h)
    assert r.status_code == 429 and "Günlük" in r.json()["detail"]
    _, h2 = member("ay@ornek.com", gunluk_kota=10, aylik_kota=1)
    assert client.post("/api/v1/analyze", json=payload(ilan_no="M1"), headers=h2).status_code == 200
    r = client.post("/api/v1/analyze", json=payload(ilan_no="M2"), headers=h2)
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
    assert r.headers["location"].endswith("/yonetim/davetler?m=eklendi_davet")
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
    assert r.headers["location"].endswith("?m=form_gecersiz") and not accounts.get_member_by_email("z@ornek.com")
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


# ------------------------------------------------------------------ gerçek tarayıcı başlıkları + davetler
CHROME_FORM = {"Origin": "null", "Sec-Fetch-Site": "same-origin"}     # Referrer-Policy: no-referrer altında Chrome


def test_real_chrome_form_post_with_null_origin_is_accepted(client, outbox):
    """Canlıda yaşanan hata: Origin 'null' gelen form POST'u sessizce reddediliyordu, üye eklenmiyordu."""
    csrf = admin_login(client, outbox)
    r = client.post("/yonetim/uye", data={"csrf": csrf, "email": "gercek@ornek.com", "gunluk": "5", "davet": "on"},
                    headers=CHROME_FORM, follow_redirects=False)
    assert r.headers["location"].endswith("/yonetim/davetler?m=eklendi_davet")
    assert accounts.get_member_by_email("gercek@ornek.com")
    assert any(m["to"] == "gercek@ornek.com" for m in outbox)


def test_cross_site_or_unknown_origin_is_rejected_with_a_visible_message(client, outbox):
    csrf = admin_login(client, outbox)
    for headers in ({"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}, {"Origin": "null"}):
        r = client.post("/yonetim/uye", data={"csrf": csrf, "email": "x1@ornek.com", "gunluk": "5"},
                        headers=headers, follow_redirects=False)
        assert r.headers["location"].endswith("?m=form_gecersiz")
    assert not accounts.get_member_by_email("x1@ornek.com")
    assert "Form doğrulanamadı" in client.get("/yonetim?m=form_gecersiz").text


def test_invites_page_shows_sent_failed_and_joined(client, outbox, monkeypatch):
    csrf = admin_login(client, outbox)
    client.post("/yonetim/uye", data={"csrf": csrf, "email": "ok@ornek.com", "gunluk": "5", "davet": "on"})
    real_send = mailer.send

    def boom(to, subject, body, html=None):
        raise mailer.MailUnavailable("E-posta gönderilemedi (SMTPAuthenticationError).")
    monkeypatch.setattr(mailer, "send", boom)
    r = client.post("/yonetim/uye", data={"csrf": csrf, "email": "kotu@ornek.com", "gunluk": "5", "davet": "on"},
                    follow_redirects=False)
    assert r.headers["location"].endswith("eklendi_davetsiz")
    client.post("/yonetim/uye", data={"csrf": csrf, "email": "davetsiz@ornek.com", "gunluk": "5"})   # davetsiz eklenen
    monkeypatch.setattr(mailer, "send", real_send)
    accounts.issue_key(accounts.get_member_by_email("ok@ornek.com")["id"])                       # ok@ katıldı
    page = client.get("/yonetim/davetler").text
    assert "ok@ornek.com" in page and "kotu@ornek.com" in page and "davetsiz@ornek.com" not in page
    assert "Katıldı" in page and "Bekliyor" in page and "SMTPAuthenticationError" in page
    assert "2 kişiye davet gönderildi; 1 kişi eklentiye giriş yaptı, 1 davet gönderilemedi" in page
    mid = accounts.get_member_by_email("kotu@ornek.com")["id"]
    r = client.post(f"/yonetim/uye/{mid}/davet?geri=davetler", data={"csrf": csrf}, follow_redirects=False)
    assert r.headers["location"].endswith("/yonetim/davetler?m=davet")
    page = client.get("/yonetim/davetler").text
    assert "2 deneme" in page and "1 davet gönderilemedi" not in page


def test_mail_failure_logs_only_the_error_type(monkeypatch, capsys):
    import smtplib
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "otoxray@cybergene.co")
    monkeypatch.setattr(settings, "smtp_port", 465)

    class Bad:
        def __init__(self, *a, **k):
            raise smtplib.SMTPAuthenticationError(535, b"sifre yanlis gizli@ornek.com")
    monkeypatch.setattr(smtplib, "SMTP_SSL", Bad)
    with pytest.raises(mailer.MailUnavailable, match="SMTPAuthenticationError"):
        mailer.send("kisi@ornek.com", "konu", "govde")
    err = capsys.readouterr().err
    assert "SMTPAuthenticationError" in err and "kisi@ornek.com" not in err and "gizli" not in err


# ------------------------------------------------------------------ hak: ilan açmak ücretsiz, aynı ilan tekrar ücretsiz
def test_opening_a_listing_preview_costs_nothing(client):
    mid, h = member(gunluk_kota=3)
    for _ in range(5):
        q = client.post("/api/v1/quick", json=payload(), headers=h).json()
    assert accounts.used_today(mid) == 0
    assert q["kota"]["limit"] == 3 and q["kota"]["kullanilan"] == 0 and q["tekrar_ucretsiz"] is False


def test_same_listing_is_charged_once_and_changed_text_is_new(client):
    mid, h = member(gunluk_kota=2)
    r = client.post("/api/v1/analyze", json=payload(), headers=h).json()
    assert r["hak_kullanildi"] is True and accounts.used_today(mid) == 1
    for _ in range(3):                                       # yeniden analiz / başka cihaz: ücretsiz
        r = client.post("/api/v1/analyze", json=payload(), headers=h).json()
        assert r["hak_kullanildi"] is False
    assert accounts.used_today(mid) == 1
    assert client.post("/api/v1/quick", json=payload(), headers=h).json()["tekrar_ucretsiz"] is True
    r = client.post("/api/v1/analyze", json=payload(aciklama="Açıklama güncellendi: tramer 5.000 TL."), headers=h).json()
    assert r["hak_kullanildi"] is True and accounts.used_today(mid) == 2


def test_free_repeat_works_even_when_daily_quota_is_full(client):
    _, h = member(gunluk_kota=1)
    assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 200
    assert client.post("/api/v1/analyze", json=payload(ilan_no="YENI"), headers=h).status_code == 429
    assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 200   # daha önce ödenmiş ilan


def test_failed_analysis_is_not_remembered_as_paid(client):
    mid, h = member(gunluk_kota=2)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: DownLLM()
    client.post("/api/v1/analyze", json=payload(), headers=h)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    r = client.post("/api/v1/analyze", json=payload(), headers=h).json()
    assert r["hak_kullanildi"] is True and accounts.used_today(mid) == 1


def test_charge_record_holds_only_a_hash(client):
    _, h = member()
    client.post("/api/v1/analyze", json=payload(aciklama="Gizli satıcı metni 12345"), headers=h)
    dump = str(list(sqlite3.connect(settings.xray_accounts_db).execute("SELECT * FROM charges")))
    assert "Gizli" not in dump and "1001" not in dump


# ------------------------------------------------------------------ HTML e-postalar
def test_invite_email_is_branded_html_with_plain_text_and_real_rights(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "store_url", "https://chromewebstore.google.com/detail/otoxray/abc")
    csrf = admin_login(client, outbox)
    client.post("/yonetim/uye", data={"csrf": csrf, "email": "html@ornek.com", "ad": "Ayşe <b>", "gunluk": "12",
                                      "aylik": "200", "bitis": "2099-01-31", "davet": "on"})
    m = next(x for x in outbox if x["to"] == "html@ornek.com")
    assert "günde 12 analiz" in m["body"]                                   # düz metin yedeği
    h = m["html"]
    assert "12 analiz" in h and "200 analiz" in h and "31.01.2099 tarihine kadar" in h
    assert "Ayşe &lt;b&gt;" in h and "<b>," not in h                        # ad kaçışlı
    store = "https://chromewebstore.google.com/detail/otoxray/abc"                       # mağaza varsa tek tık: Chrome'a ekle
    assert f'href="{store}"' in h and "Chrome&#39;a ekle" in h and "Eklentiyi kurun" in h
    assert store in m["body"]
    assert "/yonetim/static/mail-logo.png" in h and "CyberOto AI" in h


def test_code_email_html_and_logo_is_public(client, outbox):
    member("kodhtml@ornek.com")
    client.post("/api/v1/auth/kod", json={"email": "kodhtml@ornek.com"})
    m = outbox[-1]
    code = last_code(outbox, "kodhtml@ornek.com")
    assert code in m["body"] and code in m["html"]
    r = client.get("/yonetim/static/mail-logo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_real_smtp_message_is_multipart_alternative(monkeypatch):
    import smtplib
    sent = {}
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "otoxray@cybergene.co")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_user", "")

    class Fake:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def send_message(self, msg): sent["msg"] = msg
    monkeypatch.setattr(smtplib, "SMTP_SSL", Fake)
    mailer.send_code("a@ornek.com", "123456")
    msg = sent["msg"]
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_calibration_report_counts_latest_outcome_per_member_and_listing(client, outbox):
    """R5.3: etiket × sonuç; aynı üye + ilan için yalnız son sonuçlu bildirim; yanlış yeşil ve kaçan aday listeleri."""
    a = accounts.create_member("k1@ornek.com")
    b = accounts.create_member("k2@ornek.com")
    accounts.add_feedback(a, "1", "ALINIR", 8.0, None, "ekspertiz_temiz", None)
    accounts.add_feedback(a, "1", "ALINIR", 8.0, None, "ekspertiz_agir_kusur", None)     # aynı ilan: son kayıt geçerli
    accounts.add_feedback(b, "1", "ALINIR", 8.0, None, "ekspertiz_temiz", None)
    accounts.add_feedback(a, "2", "ALINMAZ", 4.0, None, "ekspertiz_temiz", None)
    accounts.add_feedback(a, "3", "DUSUNULEBILIR", 6.5, "pos", None, None)               # sonuçsuz: sayılmaz
    accounts.add_feedback(b, "4", "DUSUNULEBILIR", 6.5, None, "satin_aldim", None)
    k = accounts.kalibrasyon()
    assert k["toplam"] == 4 and k["ekspertizli"] == 3
    assert k["tablo"]["ALINIR"]["ekspertiz_agir_kusur"] == 1 and k["tablo"]["ALINIR"]["ekspertiz_temiz"] == 1
    assert [r["ilan_no"] for r in k["yanlis_yesil"]] == ["1"] and [r["ilan_no"] for r in k["kacan"]] == ["2"]
    assert k["yesil_isabet"] == 0.5
    admin_login(client, outbox)
    page = client.get("/yonetim/kalibrasyon").text
    assert "Yanlış yeşil" in page and "k1@ornek.com" in page and "Satın aldı" in page
    _, h = member("k3@ornek.com")
    assert client.post("/api/v1/feedback", json={"ilan_no": "9", "etiket": "ALINIR", "sonuc": "almadim"},
                       headers=h).status_code == 200


def test_prune_removes_only_expired_technical_records(client):
    import time as _t
    mid = accounts.create_member("p@ornek.com")
    accounts.add_charge(mid, "eski")
    accounts.add_charge(mid, "yeni")
    accounts.add_feedback(mid, "1", "ALINIR", 8.0, "pos", None, None)
    with accounts.closing(accounts._conn()) as c, c:
        c.execute("UPDATE charges SET ts = ? WHERE h = 'eski'", (_t.time() - 40 * 86400,))
        c.execute("INSERT INTO usage (member_id, gun, tur, n) VALUES (?, '2020-01-01', 'analyze', 3)", (mid,))
    r = accounts.prune()
    assert r["charges"] == 1 and r["usage"] == 1
    assert accounts.charged_recently(mid, "yeni") and accounts.get_member(mid) and accounts.list_feedback()


def test_admin_password_login_lockout_and_code_fallback(client, outbox, monkeypatch):
    """Yönetici şifresi: yalnız scrypt özeti; doğru şifre oturum açar; 8 hatalı denemede 15 dk kilit; şifre boşsa kod akışı."""
    from arac_eksper.web import yonetim
    accounts.set_admin_password(ADMIN, "dogru-sifre-123")
    with accounts.closing(accounts._conn()) as c:
        h = c.execute("SELECT pw_hash FROM admin_creds").fetchone()[0]
    assert h.startswith("scrypt$") and "dogru-sifre-123" not in h
    with pytest.raises(ValueError):
        accounts.set_admin_password(ADMIN, "kisa")
    r = client.post("/yonetim/giris", data={"email": ADMIN, "sifre": "yanlis"}, follow_redirects=False)
    assert r.headers["location"].endswith("m=sifre_hatali") and "oxr_yonetim" not in r.cookies
    r = client.post("/yonetim/giris", data={"email": "baskasi@ornek.com", "sifre": "dogru-sifre-123"}, follow_redirects=False)
    assert r.headers["location"].endswith("m=sifre_hatali")                        # listede olmayan adres
    security._fails.clear()
    r = client.post("/yonetim/giris", data={"email": ADMIN, "sifre": "dogru-sifre-123"}, follow_redirects=False)
    assert r.status_code == 303 and "oxr_yonetim" in r.cookies and client.get("/yonetim").status_code == 200
    import time as _t
    for _ in range(accounts.SIFRE_KILIT_DENEME):
        assert not accounts.check_admin_password(ADMIN, "yanlis")
    assert not accounts.check_admin_password(ADMIN, "dogru-sifre-123")                 # kilitli
    assert accounts.check_admin_password(ADMIN, "dogru-sifre-123", now=_t.time() + accounts.SIFRE_KILIT_SN + 1)
    client.cookies.clear()
    client.post("/yonetim/giris", data={"email": ADMIN, "sifre": ""})                    # boş şifre → kod gönderilir
    assert last_code(outbox, ADMIN)


def test_admin_password_cli_prompts_hidden_and_checks_list(client, monkeypatch):
    from arac_eksper.cli import app
    girdiler = iter(["cli-sifresi-456", "cli-sifresi-456"])
    monkeypatch.setattr("getpass.getpass", lambda *_: next(girdiler))
    r = runner.invoke(app, ["xray", "admin-sifre", ADMIN])
    assert r.exit_code == 0 and "cli-sifresi-456" not in r.output and accounts.check_admin_password(ADMIN, "cli-sifresi-456")
    girdiler = iter(["bir-sifre-0001", "baska-sifre-02"])
    assert runner.invoke(app, ["xray", "admin-sifre", ADMIN]).exit_code != 0                     # tekrar eşleşmedi
    assert accounts.check_admin_password(ADMIN, "cli-sifresi-456")
    assert runner.invoke(app, ["xray", "admin-sifre", "yabanci@ornek.com"]).exit_code != 0        # listede değil



def test_setup_page_and_extension_zip(client, monkeypatch):
    import io as _io
    import zipfile
    r = client.get("/kurulum")
    assert r.status_code == 200 and "cyberoto-eklenti.zip" in r.text and "Kod gönder" in r.text and "<script" not in r.text
    monkeypatch.setattr(settings, "store_url", "https://chromewebstore.google.com/detail/x/abc")
    assert "Chrome Web Mağazası'nda aç" in client.get("/kurulum").text
    z = client.get("/kurulum/cyberoto-eklenti.zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(_io.BytesIO(z.content)).namelist()
    assert "manifest.json" in names and "icons/cg-ikon.png" in names and not any(n.endswith(".md") for n in names)
    assert not any(n.startswith(("arac_eksper", "tests")) or ".env" in n for n in names)          # yalnız istemci



def test_invite_without_store_links_setup_page(client, outbox):
    csrf = admin_login(client, outbox)
    client.post("/yonetim/uye", data={"csrf": csrf, "email": "k2@ornek.com", "gunluk": "5", "davet": "on"})
    m = next(x for x in outbox if x["to"] == "k2@ornek.com")
    kurulum = settings.public_url.rstrip("/") + "/kurulum"
    assert f'href="{kurulum}"' in m["html"] and "Kurulum sayfasını aç" in m["html"] and kurulum in m["body"]


def test_privacy_page_is_public(client):
    r = client.get("/gizlilik")
    assert r.status_code == 200 and "saklanmaz" in r.text and "info@cybergene.co" in r.text and "<script" not in r.text
