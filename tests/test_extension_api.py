"""Chrome eklentisi API'si (/api/v1)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from arac_eksper.analysis import identify
from arac_eksper.config.settings import settings
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import ListingSummary, MarketStats, PartState
from arac_eksper.storage import repo
from arac_eksper.storage.db import Base
from arac_eksper.storage.models import Listing, ListingSnapshot, Verdict
from arac_eksper.web import api as ext_api, app as webapp, security
from tests.helpers import DownLLM, FakeLLM

EXT = "e" * 24
H = {"Authorization": f"Bearer {EXT}"}


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    monkeypatch.setattr(settings, "panel_token", "p" * 24)
    security._fails.clear()
    webapp.app.dependency_overrides[webapp.get_db] = lambda: db
    webapp.app.dependency_overrides[ext_api.get_llm] = lambda: FakeLLM()
    with TestClient(webapp.app, base_url="http://panel.test") as c:
        yield c
    webapp.app.dependency_overrides.clear()


def seed_market(db, n=8, base=900_000):
    for i in range(n):
        repo.create_or_update_listing_summary(
            db, ListingSummary(ilan_no=f"M{i}", url="", baslik=f"Renault Megane {i}", fiyat=base + i * 1000, yil=2022,
                               km=60000, il="Bursa", ilan_tarihi=date.today()), "Renault", "Megane")


def payload(**kw):
    p = dict(ilan_no="1001", baslik="Renault Megane 1.5 dCi", fiyat=820_000, yil=2022, km=60000, il="Bursa",
             marka="Renault", model="Megane", vites="Otomatik", yakit="Dizel",
             parts={"tavan": "orijinal", "kaput": "orijinal", "sag_arka_camurluk": "degisen"},
             aciklama="Araç ilk sahibinden. Tramer kaydı yoktur.", max_butce=900_000)
    p.update(kw)
    return p


# ------------------------------------------------------------------ yetki
def test_api_closed_without_extension_token(client, monkeypatch):
    monkeypatch.setattr(settings, "extension_token", "")
    assert client.get("/api/v1/ping").status_code == 503
    monkeypatch.setattr(settings, "extension_token", "kisa")
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer kisa"}).status_code == 503


def test_auth_required_and_panel_token_or_cookie_do_not_work(client):
    assert client.get("/api/v1/ping").status_code == 401
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer " + "p" * 24}).status_code == 401
    assert client.post("/login", data={"token": "p" * 24}, follow_redirects=False).status_code == 303
    assert client.get("/api/v1/ping").status_code == 401         # panel oturumu API'ye yetki vermez
    assert client.get("/api/v1/ping", headers=H).json()["ok"] is True


def test_every_api_route_requires_auth(client):
    for path, body in (("/api/v1/analyze", payload()), ("/api/v1/batch-evaluate", {"items": []})):
        assert client.post(path, json=body).status_code == 401


def test_bruteforce_on_api_is_throttled(client):
    for _ in range(security.LOGIN_MAX_FAILS):
        assert client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"}).status_code == 429


def test_unknown_host_header_is_refused(client):
    r = client.get("/healthz", headers={"host": "evil.example"})
    assert r.status_code == 421
    assert client.get("/healthz").status_code == 200


def test_no_cors_headers_are_sent(client):
    r = client.get("/api/v1/ping", headers={**H, "Origin": "https://www.sahibinden.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ------------------------------------------------------------------ analyze
def test_analyze_returns_full_card(client, db):
    seed_market(db)
    r = client.post("/api/v1/analyze", json=payload(), headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["etiket"] == "ALINIR" and not d["beklemede"] and d["piyasa"]["n"] >= 5 and d["sapma_yuzde"] < -5
    assert d["tavsiye_teklif"] and d["ust_sinir"] and d["ekspertiz_kontrol_listesi"]
    assert {"alinti": "ilk sahibinden", "tur": "olumlu"} in d["vurgu"]
    assert "ekspertize götürmeye değer" in d["uyari"]
    assert db.query(Verdict).filter_by(ilan_no="1001").count() == 1


def test_whatsapp_text_has_opening_offer_never_upper_limit(client, db):
    seed_market(db)
    d = client.post("/api/v1/analyze", json=payload(), headers=H).json()
    wa = d["whatsapp_metni"]
    assert f"{d['tavsiye_teklif']:,}".replace(",", ".") in wa and "ekspertiz şartıyla" in wa
    assert "sağ arka camurluk değişen" in wa or "sag arka camurluk değişen" in wa
    ust = f"{d['ust_sinir']:,}".replace(",", ".")
    assert d["ust_sinir"] == d["tavsiye_teklif"] or ust not in wa


def test_no_whatsapp_text_for_red_or_pending(client, db):
    seed_market(db)
    red = client.post("/api/v1/analyze", json=payload(parts={"tavan": "boyali"}), headers=H).json()
    assert red["etiket"] == "ALINMAZ" and red["whatsapp_metni"] is None and red["tavsiye_teklif"] is None
    webapp.app.dependency_overrides[ext_api.get_llm] = lambda: DownLLM()
    p = client.post("/api/v1/analyze", json=payload(ilan_no="2002", aciklama="farkli metin"), headers=H).json()
    assert p["beklemede"] is True and p["etiket"] is None and p["whatsapp_metni"] is None and p["vurgu"] == []


def test_phone_numbers_are_masked_before_storage(client, db):
    seed_market(db)
    client.post("/api/v1/analyze", json=payload(aciklama="Arayın 0532 123 45 67 ilk sahibinden", baslik="Acil 05321234567"),
                headers=H)
    row = db.query(Verdict).filter_by(ilan_no="1001").first()
    blob = str(row.detail_json) + str(row.findings_json) + db.get(Listing, "1001").aciklama
    assert "0532" not in blob and "123 45 67" not in blob and "[telefon]" in blob


@pytest.mark.parametrize("bad", [
    {"ilan_no": "../etc/passwd"}, {"fiyat": -5}, {"fiyat": 0}, {"yil": 1800}, {"km": -1},
    {"parts": {"Bad Key!": "orijinal"}}, {"parts": {"tavan": "mükemmel"}}, {"aciklama": "x" * 8001},
    {"baslik": "x" * 201}])
def test_analyze_rejects_invalid_input(client, bad):
    assert client.post("/api/v1/analyze", json=payload(**bad), headers=H).status_code == 422


def test_server_owned_fields_cannot_be_set_by_client(client, db):
    seed_market(db)
    client.post("/api/v1/analyze", json=payload(raw_html_path="C:/x.gz", fetched_at="2000-01-01T00:00:00"), headers=H)
    row = db.get(Listing, "1001")
    assert not row.raw_html_path and row.fetched_at.year >= 2026


def test_javascript_url_is_dropped(client, db):
    client.post("/api/v1/analyze", json=payload(url="javascript:alert(1)"), headers=H)
    assert db.get(Listing, "1001").url == ""


def test_daily_llm_limit(client, db, monkeypatch):
    seed_market(db)
    monkeypatch.setattr(settings, "analyze_daily_limit", 0)
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 429
    monkeypatch.setattr(settings, "analyze_daily_limit", 5)
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 200
    monkeypatch.setattr(settings, "analyze_daily_limit", 1)       # önbellekteki aynı metin sınıra takılmaz
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 200


def test_unknown_model_gets_no_market_and_cannot_be_green(client, db):
    seed_market(db)
    d = client.post("/api/v1/analyze", json=payload(marka=None, model=None, baslik="Bilinmeyen Araba X"), headers=H).json()
    assert d["etiket"] != "ALINIR" and d["piyasa"]["n"] == 0


# ------------------------------------------------------------------ batch
def items(*rows):
    return [dict(ilan_no=no, baslik="Renault Megane 1.5", fiyat=f, yil=2022, km=60000, il="Bursa") for no, f in rows]


def test_batch_badges_cover_all_bands(client, db):
    seed_market(db)   # medyan ~903.500
    r = client.post("/api/v1/batch-evaluate", headers=H, json={
        "items": items(("A1", 795_000), ("A2", 840_000), ("A3", 905_000), ("A4", 1_000_000), ("A5", 600_000)),
        "page_path": "/renault-megane"})
    got = {s["ilan_no"]: s for s in r.json()["sonuclar"]}
    assert got["A1"]["rozet"] == "avantajli" and got["A1"]["sapma_yuzde"] < -10
    assert got["A2"]["rozet"] == "avantajli"
    assert got["A3"]["rozet"] == "piyasada"
    assert got["A4"]["rozet"] == "pahali"
    assert got["A5"]["rozet"] == "cok_ucuz_suphe" and "nedenini sor" in got["A5"]["rozet_metin"]
    assert all("kelepir" not in s["rozet_metin"].lower() for s in got.values())


def test_batch_with_few_comparables_says_so(client, db):
    seed_market(db, n=2)
    s = client.post("/api/v1/batch-evaluate", headers=H, json={"items": items(("B1", 700_000)), "remember": False}
                    ).json()["sonuclar"][0]
    assert s["rozet"] == "emsal_yetersiz" and s["emsal_n"] <= 2


def test_batch_unidentified_rows_are_neither_badged_nor_remembered(client, db):
    seed_market(db)
    it = [dict(ilan_no="Z1", baslik="Tanınmayan Marka Z", fiyat=500_000, yil=2022, km=60000)]
    r = client.post("/api/v1/batch-evaluate", headers=H, json={"items": it}).json()
    assert r["sonuclar"][0]["rozet"] == "emsal_yetersiz" and r["kaydedilen"] == 0 and db.get(Listing, "Z1") is None


def test_batch_remembers_page_rows_once_without_snapshot_bloat(client, db):
    body = {"items": items(("C1", 900_000), ("C2", 910_000)), "page_path": "/renault-megane"}
    assert client.post("/api/v1/batch-evaluate", headers=H, json=body).json()["kaydedilen"] == 2
    client.post("/api/v1/batch-evaluate", headers=H, json=body)
    assert db.query(ListingSnapshot).filter_by(ilan_no="C1").count() == 1
    body["items"][0]["fiyat"] = 880_000
    client.post("/api/v1/batch-evaluate", headers=H, json=body)
    assert db.query(ListingSnapshot).filter_by(ilan_no="C1").count() == 2     # fiyat değişince yeni kayıt


def test_batch_limits_and_km_warning(client, db):
    assert client.post("/api/v1/batch-evaluate", headers=H, json={"items": []}).status_code == 422
    big = {"items": items(*[(f"N{i}", 900_000) for i in range(81)])}
    assert client.post("/api/v1/batch-evaluate", headers=H, json=big).status_code == 422
    it = [dict(ilan_no="K1", baslik="Renault Megane", fiyat=800_000, yil=2022, km=300_000)]
    s = client.post("/api/v1/batch-evaluate", headers=H, json={"items": it, "remember": False}).json()["sonuclar"][0]
    assert s["km_uyari"] is True


def test_batch_does_not_call_the_llm(client, db):
    class Boom:
        def parse_structured(self, *a, **k):
            raise AssertionError("batch LLM çağırmamalı")
    webapp.app.dependency_overrides[ext_api.get_llm] = lambda: Boom()
    seed_market(db)
    assert client.post("/api/v1/batch-evaluate", headers=H, json={"items": items(("D1", 800_000))}).status_code == 200


# ------------------------------------------------------------------ birimler
def test_identify_resolution_order():
    assert identify.from_path("/renault-megane?pagingOffset=20") == ("Renault", "Megane")
    assert identify.from_path("/yok-boyle-bir-sey") == (None, None)
    assert identify.from_title("2022 RENAULT MEGANE 1.5 dCi Touch") == ("Renault", "Megane")
    assert identify.from_title("Sıfır ayarında Togg") == (None, None)
    assert identify.resolve("BMW", "320i", "x", "/renault-megane") == ("BMW", "320i")     # açık alan kazanır


def test_whatsapp_helper_directly():
    from arac_eksper.schemas import Verdict
    from tests.test_hard_fails import _detail
    d = _detail(parts={"tavan": PartState.ORIGINAL, "on_tampon": PartState.PAINTED, "sol_kapi": PartState.REPLACED})
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=7, veri_tamlik=1, tavsiye_teklif=810_000,
                ust_sinir=830_000, piyasa=MarketStats(n=9, medyan=900000, p25=1, p75=2, guven="yuksek"))
    t = whatsapp_text(d, v)
    assert "810.000 TL" in t and "830" not in t and "sol kapi değişen" in t and "tampon" not in t
