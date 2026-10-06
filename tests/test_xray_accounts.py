"""Davetli kullanıcılar: kişi başı anahtar, iptal, günlük kota, hak iadesi, geri bildirim; ilan içeriği saklanmaz."""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, api, security, xray_app
from tests.helpers import DownLLM, FakeLLM
from tests.test_xray_api import EXT, H, payload

runner = CliRunner()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    api._calls.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        yield c
    xray_app.app.dependency_overrides.clear()


def user(kota=None):
    uid, key = accounts.create_user("Deneme", kota)
    return uid, {"Authorization": f"Bearer {key}"}


def test_key_is_shown_once_and_only_its_hash_is_stored():
    uid, key = accounts.create_user("Ali")
    assert key.startswith("oxr_") and len(key) > 30
    raw = sqlite3.connect(settings.xray_accounts_db).execute("SELECT * FROM users").fetchall()
    assert key not in str(raw) and accounts.hash_key(key) in str(raw)
    assert accounts.find_by_key(key)["id"] == uid and accounts.find_by_key(key + "x") is None


def test_personal_key_works_and_revoked_key_is_rejected(client):
    uid, h = user()
    r = client.get("/api/v1/ping", headers=h).json()
    assert r["kullanici"] == "Deneme" and r["kota"] == {"limit": settings.user_daily_quota, "kullanilan": 0}
    assert accounts.revoke(uid)
    assert client.get("/api/v1/ping", headers=h).status_code == 401


def test_daily_quota_per_user(client):
    _, h = user(kota=2)
    for _ in range(2):
        r = client.post("/api/v1/analyze", json=payload(), headers=h)
        assert r.status_code == 200
    assert r.json()["kota"] == {"limit": 2, "kullanilan": 2}
    assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 429
    _, other = user(kota=2)                               # kota kişiye özel
    assert client.post("/api/v1/analyze", json=payload(), headers=other).status_code == 200


def test_failed_llm_refunds_the_quota(client):
    uid, h = user(kota=1)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: DownLLM()
    assert client.post("/api/v1/analyze", json=payload(), headers=h).json()["beklemede"] is True
    assert accounts.used_today(uid) == 0
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    assert client.post("/api/v1/analyze", json=payload(), headers=h).status_code == 200


def test_batch_and_quick_are_limited_against_bulk_copying(client, monkeypatch):
    monkeypatch.setattr(settings, "user_daily_batch", 1)
    _, h = user()
    body = {"items": [dict(ilan_no="A", fiyat=800_000, yil=2022, km=60000)]}
    assert client.post("/api/v1/batch-evaluate", json=body, headers=h).status_code == 200
    assert client.post("/api/v1/batch-evaluate", json=body, headers=h).status_code == 429
    assert client.post("/api/v1/quick", json=payload(), headers=h).status_code == 200
    assert client.post("/api/v1/quick", json=payload(), headers=h).status_code == 429
    assert client.post("/api/v1/batch-evaluate", json=body, headers=H).status_code == 200   # sahip kotasız


def test_owner_never_touches_the_accounts_db(client):
    client.post("/api/v1/analyze", json=payload(), headers=H)
    client.post("/api/v1/feedback", json={"ilan_no": "1001", "oy": "pos"}, headers=H)
    import pathlib
    assert not pathlib.Path(settings.xray_accounts_db).exists()


def test_feedback_stored_without_listing_content_and_phone_masked(client):
    uid, h = user()
    r = client.post("/api/v1/feedback", headers=h, json={
        "ilan_no": "1001", "etiket": "ALINIR", "skor": 8.1, "oy": "neg", "sonuc": "ekspertiz_agir_kusur",
        "notu": "Ekspertizde şase işlemli çıktı, satıcı 0532 123 45 67"})
    assert r.status_code == 200 and r.json()["kaydedildi"] is True
    fb = accounts.list_feedback()[0]
    assert fb["user_id"] == uid and fb["sonuc"] == "ekspertiz_agir_kusur" and fb["oy"] == "neg"
    assert "0532" not in fb["notu"] and "[telefon]" in fb["notu"]
    cols = {d[1] for d in sqlite3.connect(settings.xray_accounts_db).execute("PRAGMA table_info(feedback)")}
    assert not cols & {"aciklama", "baslik", "fiyat", "url", "parts"}


@pytest.mark.parametrize("body", [
    {"ilan_no": "1001"},                                   # içerik yok
    {"ilan_no": "1001", "oy": "belki"},
    {"ilan_no": "1001", "sonuc": "uydurma"},
    {"ilan_no": "x" * 30, "oy": "pos"},
    {"ilan_no": "1001", "notu": "a" * 501},
])
def test_feedback_validation(client, body):
    _, h = user()
    assert client.post("/api/v1/feedback", json=body, headers=h).status_code == 422


def test_feedback_requires_auth_and_is_rate_limited(client, monkeypatch):
    assert client.post("/api/v1/feedback", json={"ilan_no": "1", "oy": "pos"}).status_code == 401
    monkeypatch.setattr(settings, "feedback_daily_limit", 1)
    _, h = user()
    assert client.post("/api/v1/feedback", json={"ilan_no": "1", "oy": "pos"}, headers=h).status_code == 200
    assert client.post("/api/v1/feedback", json={"ilan_no": "2", "oy": "pos"}, headers=h).status_code == 429


def test_cli_user_lifecycle():
    r = runner.invoke(cli.app, ["xray", "user", "add", "Ayşe", "--kota", "5"])
    assert r.exit_code == 0, r.output
    key = next(w for w in r.output.split() if w.startswith("oxr_"))
    out = runner.invoke(cli.app, ["xray", "user", "list"]).output
    assert "Ayşe" in out and key not in out and key[:10] in out
    uid = accounts.find_by_key(key)["id"]
    assert runner.invoke(cli.app, ["xray", "user", "quota", str(uid), "9"]).exit_code == 0
    assert accounts.find_by_key(key)["gunluk_kota"] == 9
    assert runner.invoke(cli.app, ["xray", "user", "revoke", str(uid)]).exit_code == 0
    assert accounts.find_by_key(key) is None
    assert runner.invoke(cli.app, ["xray", "user", "revoke", str(uid)]).exit_code == 3


def test_cli_feedback_list_json():
    uid, _ = accounts.create_user("Veli")
    accounts.add_feedback(uid, "42", "DUSUNULEBILIR", 6.0, "pos", None, "iyi")
    r = runner.invoke(cli.app, ["xray", "feedback", "--json"])
    assert r.exit_code == 0 and '"ilan_no": "42"' in r.stdout


def test_rule_weights_trace_only_for_owner(client):
    _, h = user()
    assert client.post("/api/v1/analyze", json=payload(), headers=h).json()["trace"] == []
    assert client.post("/api/v1/analyze", json=payload(), headers=H).json()["trace"]
