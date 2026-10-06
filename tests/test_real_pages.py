"""R0.2: eklentinin gerçek okuma kodu (extract-detail.js) GERÇEK ilan sayfalarında (tests/fixtures/real, kişisel veriden
arındırılmış) doğru okuyor mu? Beklenen değerler sayfadan Python ile BAĞIMSIZ okunur (dt/dd + hasar şeması sınıfları).
Siteye istek atılmaz: sayfalar yerelden verilir. Chromium gerekir."""
import pathlib
import re

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "real"
LIB = ROOT / "extension" / "lib"
DOMAIN = "sahib" + "inden.com"
PAGES = sorted(FX.glob("detail_*.html"))
PART_CLASS = {"front-bumper": "on_tampon", "rear-bumper": "arka_tampon", "front-hood": "motor_kaputu",
              "rear-hood": "bagaj_kapagi", "roof": "tavan", "front-left-mudguard": "sol_on_camurluk",
              "front-right-mudguard": "sag_on_camurluk", "rear-left-mudguard": "sol_arka_camurluk",
              "rear-right-mudguard": "sag_arka_camurluk", "front-left-door": "sol_on_kapi",
              "front-right-door": "sag_on_kapi", "rear-left-door": "sol_arka_kapi", "rear-right-door": "sag_arka_kapi"}
STATE_CLASS = {"original-new": "orijinal", "painted-new": "boyali", "localpainted-new": "lokal_boyali", "changed-new": "degisen"}

pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not PAGES, reason="gerçek fixture yok")]


def expected(path: pathlib.Path) -> dict:
    """Sayfanın kendisinden bağımsız okuma (eklenti kodundan farklı yol)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    info = {" ".join(it.find("dt").get_text(" ", strip=True).split()): " ".join(it.find("dd").get_text(" ", strip=True).split())
            for it in soup.select("dl.classifiedInfoList .classifiedInfoItem")}
    digits = lambda s: int(re.sub(r"\D", "", s))
    parts = {}
    for d in soup.select(".car-parts > div"):
        c = d.get("class") or []
        name = next((PART_CLASS[x] for x in c if x in PART_CLASS), None)
        state = next((STATE_CLASS[x] for x in c if x in STATE_CLASS), None)
        if name and state:
            parts[name] = state
    return {"ilan_no": info["İlan No"], "yil": digits(info["Yıl"]), "km": digits(info["KM"]), "marka": info["Marka"],
            "seri": info["Seri"], "paket": info["Model"], "vites": info["Vites"], "yakit": info["Yakıt / Motor Tipi"],
            "agir": info["Ağır Hasar Kayıtlı"] == "Evet", "parts": parts}


@pytest.fixture(scope="module")
def extracted():
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        site_hits = []

        def route(r):
            url = r.request.url
            if DOMAIN in url and "/ilan/" in url:
                no = re.search(r"(\d{10})", url).group(1)
                return r.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body=(FX / f"detail_{no}.html").read_text(encoding="utf-8"))
            site_hits.append(url)
            return r.abort()
        pg.route("**/*", route)
        for f in PAGES:
            no = f.stem.split("_")[1]
            pg.goto(f"https://www.{DOMAIN}/ilan/vasita-otomobil-gercek-{no}/detail")
            for js in ("selectors.js", "privacy.js", "extract-detail.js"):
                pg.add_script_tag(content=(LIB / js).read_text(encoding="utf-8"))
            out[no] = pg.evaluate("() => { const r = AracX.extractDetail(document, location); return {ok: r.ok, eksik: r.eksik, uyarilar: r.uyarilar, p: r.payload}; }")
        b.close()
    return out


def test_every_real_page_is_read(extracted):
    assert len(extracted) == len(PAGES) >= 13
    bad = {no: r["eksik"] for no, r in extracted.items() if not r["ok"]}
    assert bad == {}


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.stem)
def test_fields_match_independent_reading(extracted, path):
    exp, got = expected(path), extracted[path.stem.split("_")[1]]["p"]
    assert got["ilan_no"] == exp["ilan_no"]
    assert (got["yil"], got["km"]) == (exp["yil"], exp["km"])
    assert (got["marka"], got["seri"], got["paket"]) == (exp["marka"], exp["seri"], exp["paket"])
    assert (got["vites"], got["yakit"]) == (exp["vites"], exp["yakit"])
    assert got["agir_hasar_kayitli"] is exp["agir"]
    assert got["fiyat"] > 10_000 and len(got["aciklama"]) > 20
    assert got["parts"] == exp["parts"] and len(got["parts"]) == 13             # hasar şeması tam okunur


def test_known_damage_page(extracted):
    p = extracted["1343955761"]["p"]["parts"]
    assert (p["motor_kaputu"], p["sag_on_camurluk"], p["sag_on_kapi"], p["tavan"]) == ("boyali", "degisen", "lokal_boyali", "orijinal")
    assert extracted["1343969213"]["p"]["agir_hasar_kayitli"] is True              # başlıkta da "Ağır Hasar Kayıtlı"


def test_server_accepts_every_real_payload(extracted, monkeypatch):
    from arac_eksper.config.settings import settings
    from arac_eksper.web import api, security, xray_app
    from tests.helpers import FakeLLM
    monkeypatch.setattr(settings, "extension_token", "r" * 24)
    security._fails.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    try:
        with TestClient(xray_app.app, base_url="http://panel.test") as c:
            for no, r in extracted.items():
                res = c.post("/api/v1/quick", json=r["p"], headers={"Authorization": "Bearer " + "r" * 24})
                assert res.status_code == 200, (no, res.text[:300])
                v = c.post("/api/v1/analyze", json=r["p"], headers={"Authorization": "Bearer " + "r" * 24}).json()
                assert "parça diyagramı yok / parçalar bilinmiyor" not in " ".join(v["eksiler"]), no
    finally:
        xray_app.app.dependency_overrides.clear()


def test_real_fixtures_hold_no_personal_data():
    for f in PAGES:
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"\b0?5\d{2}[ -]\d{3}[ -]?\d{2}[ -]?\d{2}\b", t), f.name
        assert not re.search(r"data-(lat|lon|lng)=", t, re.I), f.name
        assert "classifiedUserBox" not in t and "for-classified-owner" not in t, f.name


def test_price_matches_page(extracted):
    for f in PAGES:
        soup = BeautifulSoup(f.read_text(encoding="utf-8"), "lxml")
        page_price = int(re.sub(r"\D", "", soup.select_one(".classifiedInfo h3").get_text()))
        assert extracted[f.stem.split("_")[1]]["p"]["fiyat"] == page_price, f.name


def test_kb_gearbox_items_match_a_real_listing_once_approved():
    """Gerçek Megane ilanında (1.5 dCi, Otomatik, 88.000 km) şanzıman türü yazmıyor: madde vites+model+yıl ile eşleşmeli."""
    from datetime import datetime, timezone
    from arac_eksper.analysis import models_kb
    from arac_eksper.schemas import ListingDetail
    e = expected(FX / "detail_1343974334.html")
    d = ListingDetail(ilan_no=e["ilan_no"], url="", baslik="", marka=e["marka"], model=e["seri"], seri=e["seri"],
                      paket=e["paket"], vites=e["vites"], yakit=e["yakit"], fiyat=1, yil=e["yil"], km=e["km"], il="",
                      ilan_tarihi=datetime.now().date(), aciklama="", fetched_at=datetime.now(timezone.utc), parts=e["parts"])
    kb = [dict(x, onayli=True) for x in models_kb.load_kb(include_unapproved=True)]   # onay simülasyonu
    names = {k["etiket"]: k["tetiklendi"] for k in models_kb.kronik_arizalar(d, kb)}
    assert names.get("EDC şanzıman kavrama aşınması") is False                       # eşleşti, 88k < 100k eşik
    assert "1.5 dCi DPF/EGR tıkanması" in names
    assert models_kb.kronik_arizalar(d, models_kb.load_kb()) == []                    # onaysız: etkisiz
