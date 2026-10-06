"""CyberOto AI API: durumsuzluk, yetki, KVKK, sıfır depolama, yasal uyarı."""
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from arac_eksper.config.settings import settings
from arac_eksper.report.legal import DISCLAIMER
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import MarketStats, PartState
from arac_eksper.web import api, security, xray_app
from tests.helpers import DownLLM, FakeLLM

EXT = "e" * 24
H = {"Authorization": f"Bearer {EXT}"}
EXACT = ("Bu yazılım bir yapay zeka metin analizi ve karar destek aracıdır. Resmi ekspertiz raporu niteliği taşımaz. "
         "Nihai alım-satım ve mekanik kontrollerden kullanıcı sorumludur.")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    api._calls.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        yield c
    xray_app.app.dependency_overrides.clear()


def comps(n=8, base=900_000):
    return [dict(id=f"M{i}", yil=2022, km=60000, fiyat=base + i * 1000) for i in range(n)]


def payload(**kw):
    p = dict(ilan_no="1001", baslik="Renault Megane 1.5 dCi", fiyat=820_000, yil=2022, km=60000, marka="Renault",
             model="Megane", vites="Otomatik", yakit="Dizel",
             parts={"tavan": "orijinal", "kaput": "orijinal", "sag_arka_camurluk": "degisen"},
             aciklama="Araç ilk sahibinden. Tramer kaydı yoktur.", max_butce=900_000, emsal=comps())
    p.update(kw)
    return p


# ------------------------------------------------------------------ yasal / mimari sınırlar
def test_disclaimer_text_is_exact():
    assert DISCLAIMER == EXACT


def test_disclaimer_in_every_report(client):
    for r in (client.post("/api/v1/analyze", json=payload(), headers=H).json(),
              client.post("/api/v1/batch-evaluate", headers=H,
                          json={"items": [dict(ilan_no="A", fiyat=800_000, yil=2022, km=60000)], "emsal": comps()}).json(),
              client.get("/api/v1/ping", headers=H).json()):
        assert r["yasal_uyari"] == EXACT
    xray_app.app.dependency_overrides[api.get_llm] = lambda: DownLLM()
    assert client.post("/api/v1/analyze", json=payload(aciklama="baska metin"), headers=H).json()["yasal_uyari"] == EXACT


def test_api_app_imports_no_scraper_database_or_panel_code():
    """Sunucu tarafında ilan sayfası çeken/saklayan hiçbir kod yüklenmemeli (yeni süreçte denetlenir)."""
    code = ("import sys, arac_eksper.web.xray_app\n"
            "bad = [m for m in sys.modules if m.split('.')[0] in ('playwright','sqlalchemy','alembic','apscheduler','bs4','lxml','requests')"
            " or m.startswith(('arac_eksper.collector','arac_eksper.storage','arac_eksper.watcher','arac_eksper.parser',"
            "'arac_eksper.web.app','arac_eksper.web.service','arac_eksper.pipeline','arac_eksper.report.telegram'))]\n"
            "print(bad)\nsys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nothing_is_written_to_disk_or_db(client, tmp_path, monkeypatch):
    """Durumsuz: istek sırasında yeni dosya oluşmaz, DB motoru hiç kurulmaz."""
    import os
    monkeypatch.chdir(tmp_path)
    client.post("/api/v1/analyze", json=payload(), headers=H)
    client.post("/api/v1/batch-evaluate", headers=H, json={"items": [dict(ilan_no="A", fiyat=1, yil=2022, km=1)]})
    assert os.listdir(tmp_path) == []
    src = open(api.__file__, encoding="utf-8").read()
    for yasak in ("storage", "sqlalchemy", "open(", "write(", "logging", "print("):
        assert yasak not in src, yasak


def test_no_brand_name_in_product_code():
    """Ürün kodunda/arayüzünde ilan sitesinin adı geçmez (alan adı yalnızca manifest eşleşmesi ve tek sabit dosyada)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    brand = "sahib" + "inden"
    allowed = {root / "extension" / "manifest.json", root / "extension" / "lib" / "site.js"}
    files = [*root.glob("extension/**/*"), root / "arac_eksper/web/api.py", root / "arac_eksper/web/xray_app.py",
             root / "arac_eksper/report/legal.py", root / "arac_eksper/report/offer_text.py",
             root / "arac_eksper/analysis/market_calc.py"]
    leaks = []
    for f in files:
        if f.is_file() and f not in allowed and "tests" not in f.parts and f.suffix in {".js", ".html", ".css", ".json", ".md", ".py"}:
            if brand in f.read_text("utf-8", errors="ignore").lower():
                leaks.append(str(f.relative_to(root)))
    assert leaks == [], leaks


def test_product_name_is_cyberoto():
    import json
    import pathlib
    m = json.loads((pathlib.Path(__file__).resolve().parent.parent / "extension/manifest.json").read_text("utf-8"))
    assert m["name"] == "CyberOto AI"


# ------------------------------------------------------------------ yetki
def test_api_closed_without_token(client, monkeypatch):
    monkeypatch.setattr(settings, "extension_token", "")
    assert client.get("/api/v1/ping").status_code == 503
    monkeypatch.setattr(settings, "extension_token", "kisa")
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer kisa"}).status_code == 503


def test_server_refuses_to_start_without_token(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", "")
    with pytest.raises(RuntimeError):
        with TestClient(xray_app.app):
            pass


def test_auth_required(client):
    assert client.get("/api/v1/ping").status_code == 401
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    for path, body in (("/api/v1/analyze", payload()), ("/api/v1/batch-evaluate", {"items": []})):
        assert client.post(path, json=body).status_code == 401


def test_bruteforce_throttled_unknown_host_refused_no_cors(client):
    for _ in range(security.LOGIN_MAX_FAILS):
        client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"})
    assert client.get("/api/v1/ping", headers={"Authorization": "Bearer yanlis"}).status_code == 429
    assert client.get("/healthz", headers={"host": "evil.example"}).status_code == 421
    r = client.get("/healthz", headers={"Origin": "https://example.org"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ------------------------------------------------------------------ analyze
def test_analyze_returns_full_card_with_local_comparables(client):
    d = client.post("/api/v1/analyze", json=payload(), headers=H).json()
    assert d["etiket"] == "ALINIR" and d["piyasa"]["n"] >= 5 and d["sapma_yuzde"] < -5
    assert d["tavsiye_teklif"] and d["ust_sinir"] and d["ekspertiz_kontrol_listesi"]
    assert {"alinti": "ilk sahibinden", "tur": "olumlu"} in d["vurgu"]
    assert "ekspertize götürmeye değer" in d["uyari"]


def test_no_comparables_means_no_green_but_still_an_honest_offer(client):
    d = client.post("/api/v1/analyze", json=payload(emsal=[]), headers=H).json()
    assert d["etiket"] != "ALINIR" and d["piyasa"]["n"] == 0 and d["piyasa"]["medyan"] == 0
    t = d["teklif"]
    assert t["kaynak"] == "ilan" and "Piyasa verisi yok" in t["dayanak"][0]               # piyasa fiyatı UYDURULMADI
    assert d["tavsiye_teklif"] == t["acilis"] and t["acilis"] <= t["hedef"] <= t["ust_sinir"] <= 820_000
    assert d["whatsapp_metni"] and "TL teklif" in d["whatsapp_metni"]


def test_card_carries_market_average_range_and_offer_basis(client):
    d = client.post("/api/v1/analyze", json=payload(), headers=H).json()
    p = d["piyasa"]
    assert p["medyan"] > 0 and p["p25"] <= p["medyan"] <= p["p75"] and p["min_emsal"] == 5 and p["n"] >= 5
    t = d["teklif"]
    assert t["kaynak"] == "piyasa" and any("Piyasa ortalaması" in x for x in t["dayanak"])
    assert t["acilis"] <= t["hedef"] <= t["ust_sinir"] and d["ust_sinir"] == t["ust_sinir"]


def test_zero_km_car_still_finds_comparables(client):
    """km=0'da bant sıfıra düşüyordu ('Henüz emsal yok'): en az ±10.000 km bandı uygulanır."""
    e = [dict(id=f"N{i}", yil=2025, km=500 * i, fiyat=4_000_000 + i * 10_000, seri="Vito") for i in range(6)]
    d = client.post("/api/v1/analyze", json=payload(yil=2025, km=0, fiyat=4_200_000, seri="Vito", emsal=e, max_butce=None),
                    headers=H).json()
    assert d["piyasa"]["n"] >= 5


def test_own_id_is_excluded_from_comparables(client):
    own = comps() + [dict(id="1001", yil=2022, km=60000, fiyat=100)]       # kendisi emsal olamaz
    d = client.post("/api/v1/analyze", json=payload(emsal=own), headers=H).json()
    assert d["piyasa"]["n"] == 8 and d["piyasa"]["medyan"] > 800_000


def test_whatsapp_text_never_contains_upper_limit(client):
    d = client.post("/api/v1/analyze", json=payload(), headers=H).json()
    wa = d["whatsapp_metni"]
    fmt = lambda n: f"{n:,}".replace(",", ".")
    assert fmt(d["tavsiye_teklif"]) in wa and "ekspertiz şartıyla" in wa and "sag arka camurluk değişen" in wa
    if d["ust_sinir"] != d["tavsiye_teklif"]:
        assert fmt(d["ust_sinir"]) not in wa


def test_red_and_pending_have_no_offer_text(client):
    red = client.post("/api/v1/analyze", json=payload(parts={"tavan": "boyali"}), headers=H).json()
    assert red["etiket"] == "ALINMAZ" and red["whatsapp_metni"] is None and red["tavsiye_teklif"] is None
    xray_app.app.dependency_overrides[api.get_llm] = lambda: DownLLM()
    p = client.post("/api/v1/analyze", json=payload(aciklama="farkli metin"), headers=H).json()
    assert p["beklemede"] is True and p["etiket"] is None and p["whatsapp_metni"] is None and p["vurgu"] == []


def test_phone_numbers_masked_before_reaching_the_llm(client):
    seen = {}

    class Spy(FakeLLM):
        def parse_structured(self, s, u, m, model_name=None):
            seen["u"] = u
            return super().parse_structured(s, u, m, model_name)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: Spy()
    client.post("/api/v1/analyze", json=payload(aciklama="Arayın 0532 123 45 67 ilk sahibinden", baslik="Acil 05321234567"), headers=H)
    assert "0532" not in seen["u"] and "[telefon]" in seen["u"]


@pytest.mark.parametrize("bad", [
    {"ilan_no": "../etc/passwd"}, {"fiyat": -5}, {"yil": 1800}, {"km": -1}, {"parts": {"Bad Key!": "orijinal"}},
    {"parts": {"tavan": "mükemmel"}}, {"aciklama": "x" * 8001}, {"baslik": "x" * 201}, {"emsal": comps(301)},
    {"emsal": [dict(id="!", yil=2022, km=1, fiyat=1)]}])
def test_invalid_input_rejected(client, bad):
    assert client.post("/api/v1/analyze", json=payload(**bad), headers=H).status_code == 422


def test_url_and_personal_fields_are_ignored_not_processed(client):
    seen = {}

    class Spy(FakeLLM):
        def parse_structured(self, s, u, m, model_name=None):
            seen["u"] = u
            return super().parse_structured(s, u, m, model_name)
    xray_app.app.dependency_overrides[api.get_llm] = lambda: Spy()
    r = client.post("/api/v1/analyze", json=payload(url="https://x.example/ilan/1", satici_adi="Ahmet Yilmaz",
                                                    telefon="05321234567"), headers=H)
    assert r.status_code == 200 and "Ahmet" not in seen["u"] and "05321234567" not in seen["u"]
    assert "satici" not in str(api.AnalyzeRequest.model_fields) and "url" not in api.AnalyzeRequest.model_fields


def test_daily_limit_counts_calls_only(client, monkeypatch):
    monkeypatch.setattr(settings, "analyze_daily_limit", 2)
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 200
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 200
    assert client.post("/api/v1/analyze", json=payload(), headers=H).status_code == 429
    assert all(isinstance(t, float) for t in api._calls)         # yalnız zaman damgası, içerik yok


# ------------------------------------------------------------------ batch
def test_batch_badges_cover_all_bands(client):
    items = [dict(ilan_no=n, fiyat=f, yil=2022, km=60000) for n, f in
             (("A1", 795_000), ("A2", 840_000), ("A3", 905_000), ("A4", 1_000_000), ("A5", 600_000))]
    r = client.post("/api/v1/batch-evaluate", headers=H, json={"items": items, "emsal": comps()}).json()
    got = {s["ilan_no"]: s for s in r["sonuclar"]}
    assert got["A1"]["rozet"] == "avantajli" and got["A1"]["sapma_yuzde"] < -10
    assert got["A2"]["rozet"] == "avantajli" and got["A3"]["rozet"] == "piyasada" and got["A4"]["rozet"] == "pahali"
    assert got["A5"]["rozet"] == "cok_ucuz_suphe" and "nedenini sor" in got["A5"]["rozet_metin"]
    assert all("kelepir" not in s["rozet_metin"].lower() for s in got.values())


def test_batch_few_comparables_and_km_warning(client):
    s = client.post("/api/v1/batch-evaluate", headers=H, json={
        "items": [dict(ilan_no="B1", fiyat=700_000, yil=2022, km=300_000)], "emsal": comps(2)}).json()["sonuclar"][0]
    assert s["rozet"] == "emsal_yetersiz" and s["km_uyari"] is True and "Benzer ilan az" in s["rozet_metin"]


def test_batch_limits_and_no_llm(client):
    assert client.post("/api/v1/batch-evaluate", headers=H, json={"items": []}).status_code == 422
    big = {"items": [dict(ilan_no=f"N{i}", fiyat=9, yil=2022, km=1) for i in range(81)]}
    assert client.post("/api/v1/batch-evaluate", headers=H, json=big).status_code == 422

    class Boom:
        def parse_structured(self, *a, **k):
            raise AssertionError("batch LLM çağırmamalı")
    xray_app.app.dependency_overrides[api.get_llm] = lambda: Boom()
    assert client.post("/api/v1/batch-evaluate", headers=H,
                       json={"items": [dict(ilan_no="D1", fiyat=800_000, yil=2022, km=60000)], "emsal": comps()}).status_code == 200


# ------------------------------------------------------------------ birimler
def test_market_calc_narrow_wide_and_self_exclusion():
    from arac_eksper.analysis.market_calc import stats_from_comparables
    c = [(f"x{i}", 2022, 60000, 900_000 + i) for i in range(8)]
    assert stats_from_comparables("t", 2022, 60000, c).guven == "yuksek"
    few = stats_from_comparables("t", 2021, 70000, c[:3] + [("f", 2020, 80000, 900_003)])
    assert few.guven == "dusuk" and few.n == 4
    assert stats_from_comparables("x0", 2022, 60000, c).n == 7
    assert stats_from_comparables("t", 2022, 60000, []).guven == "yok"


def test_whatsapp_helper_directly():
    from arac_eksper.schemas import Verdict
    from tests.test_hard_fails import _detail
    d = _detail(parts={"tavan": PartState.ORIGINAL, "on_tampon": PartState.PAINTED, "sol_kapi": PartState.REPLACED})
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=7, veri_tamlik=1, tavsiye_teklif=810_000,
                ust_sinir=830_000, piyasa=MarketStats(n=9, medyan=900000, p25=1, p75=2, guven="yuksek"))
    t = whatsapp_text(d, v)
    assert "810.000 TL" in t and "830" not in t and "sol kapi değişen" in t and "tampon" not in t


def test_every_extension_script_is_syntactically_valid():
    """Tarayıcıda sessizce yüklenmeyen betik tüm eklentiyi bozar: her .js dosyası node ile sözdizimi denetimine girer."""
    import pathlib
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node yok")
    root = pathlib.Path(__file__).resolve().parent.parent / "extension"
    files = [f for f in root.rglob("*.js") if "tests" not in f.parts]
    assert len(files) >= 10
    for f in files:
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{f.relative_to(root)}: {r.stderr[:300]}"


def test_comparables_are_restricted_to_the_same_series():
    """Gerçek sayfada farklı seriler (Vito / Vito Tourer Select) karışınca 'avantajlı/pahalı' rozeti yanıltıyordu."""
    from arac_eksper.analysis.market_calc import stats_from_comparables
    pool = ([(f"a{i}", 2022, 60000, 900_000 + i, "Vito Tourer") for i in range(6)]
            + [(f"b{i}", 2022, 60000, 3_000_000 + i, "Vito Tourer Select") for i in range(6)])
    s = stats_from_comparables("t", 2022, 60000, pool, "VİTO  tourer")           # büyük/küçük harf, aksan, boşluk farkı yok sayılır
    assert s.n == 6 and 899_000 < s.medyan < 910_000
    assert stats_from_comparables("t", 2022, 60000, pool, "Viano").n == 0         # aynı seriden emsal yok → "emsal yetersiz"
    assert stats_from_comparables("t", 2022, 60000, pool).n == 12                  # seri bilinmiyorsa filtre yok (geri uyumlu)


def test_batch_uses_series_and_rejects_nothing_extra(client):
    emsal = [dict(id=f"A{i}", yil=2022, km=60000, fiyat=900_000 + i * 1000, seri="Megane") for i in range(8)]
    emsal += [dict(id=f"C{i}", yil=2022, km=60000, fiyat=300_000 + i * 1000, seri="Clio") for i in range(8)]
    items = [dict(ilan_no="X1", fiyat=905_000, yil=2022, km=60000, seri="Megane"),
             dict(ilan_no="X2", fiyat=310_000, yil=2022, km=60000, seri="Clio"),
             dict(ilan_no="X3", fiyat=310_000, yil=2022, km=60000, seri="Fiat Egea")]
    got = {s["ilan_no"]: s for s in client.post("/api/v1/batch-evaluate", headers=H, json={"items": items, "emsal": emsal}).json()["sonuclar"]}
    assert got["X1"]["rozet"] == "piyasada" and got["X2"]["rozet"] == "piyasada"        # Clio, Megane ile kıyaslanmadı
    assert got["X3"]["rozet"] == "emsal_yetersiz"


def test_serve_explains_a_busy_port_instead_of_a_raw_socket_error(monkeypatch, capsys):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        monkeypatch.setattr(settings, "extension_token", EXT)
        monkeypatch.setattr(settings, "xray_host", "127.0.0.1")
        monkeypatch.setattr(settings, "xray_port", s.getsockname()[1])
        with pytest.raises(SystemExit) as e:
            xray_app.serve()
    assert e.value.code == 4
    assert "kullanılıyor" in capsys.readouterr().err


# ------------------------------------------------------------------ hız: ön hesap + ikinci geçiş ayarı
def test_quick_is_instant_llm_free_and_gives_market_and_offer(client):
    class Boom:
        def parse_structured(self, *a, **k):
            raise AssertionError("quick LLM çağırmamalı")
    xray_app.app.dependency_overrides[api.get_llm] = lambda: Boom()
    r = client.post("/api/v1/quick", json=payload(), headers=H)
    d = r.json()
    assert r.status_code == 200 and d["on_hesap"] is True and "etiket" not in d            # etiket ÜRETMEZ
    assert d["piyasa"]["n"] >= 5 and d["piyasa"]["medyan"] > 0 and d["teklif"]["kaynak"] == "piyasa"
    assert d["teklif"]["acilis"] <= d["teklif"]["anlasma"] <= d["teklif"]["ust_sinir"] <= 820_000
    assert d["yasal_uyari"] == EXACT and d["elenme_nedenleri"] == []


def test_quick_finds_structural_rejections_immediately_and_offers_nothing(client):
    over_budget = client.post("/api/v1/quick", json=payload(max_butce=500_000), headers=H).json()
    assert any("bütçe" in h.lower() for h in over_budget["elenme_nedenleri"]) and over_budget["teklif"] is None
    high_km = client.post("/api/v1/quick", json=payload(km=900_000), headers=H).json()
    assert any("km" in h.lower() for h in high_km["elenme_nedenleri"])
    roof = client.post("/api/v1/quick", json=payload(parts={"tavan": "boyali"}), headers=H).json()
    assert any("Tavan" in h for h in roof["elenme_nedenleri"])


def test_quick_does_not_use_the_daily_llm_budget_and_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "analyze_daily_limit", 1)
    for _ in range(5):
        assert client.post("/api/v1/quick", json=payload(), headers=H).status_code == 200
    assert not api._calls
    assert client.post("/api/v1/quick", json=payload()).status_code == 401
    assert client.post("/api/v1/quick", json=payload(fiyat=-1), headers=H).status_code == 422


def test_analyze_honours_second_pass_setting(client, monkeypatch):
    from arac_eksper.schemas import DescriptionFindings, Evidence

    class Soft:
        calls = 0

        def parse_structured(self, s, u, m, model_name=None):
            Soft.calls += 1
            return DescriptionFindings(sase_direk_podye_islem="belirsiz", airbag="belirsiz", motor_sanziman="belirsiz",
                                       km_degisimi_suphesi=False, tramer_tutari=0,
                                       olumsuz_sinyaller=[Evidence(etiket="x", alinti="ilk sahibinden")])
    xray_app.app.dependency_overrides[api.get_llm] = lambda: Soft()
    monkeypatch.setattr(settings, "xray_second_pass", "hard")
    client.post("/api/v1/analyze", json=payload(), headers=H)
    assert Soft.calls == 1                                  # yumuşak sinyal: tek geçiş
    Soft.calls = 0
    monkeypatch.setattr(settings, "xray_second_pass", "all")
    client.post("/api/v1/analyze", json=payload(), headers=H)
    assert Soft.calls == 2


def test_manifest_is_store_ready_and_points_to_hosted_api():
    import json
    import pathlib
    m = json.loads((pathlib.Path(__file__).resolve().parent.parent / "extension/manifest.json").read_text("utf-8"))
    assert len(m["description"]) <= 132                       # Chrome Web Store sınırı
    assert m["host_permissions"][0] == "https://cyberoto.cybergene.co/*"            # 2026-10-07 alan adı
    assert "https://otoxray.cybergene.co/*" in m["host_permissions"]              # geçiş dönemi
    assert not any(p.startswith(("http://*", "https://*", "<all_urls>")) for p in m["host_permissions"])


def test_evidence_list_has_no_duplicate_quotes():
    """P.4: aynı alıntı hem olumsuz sinyal hem hard-claim olarak gelirse tek satır, özgül etiketle."""
    from arac_eksper.schemas import DescriptionFindings, Evidence
    f = DescriptionFindings(sase_direk_podye_islem="var", sase_alinti="Şase ucu işlemli", airbag="belirsiz",
                            motor_sanziman="belirsiz", km_degisimi_suphesi=False,
                            olumsuz_sinyaller=[Evidence(etiket="Şase işlemi", alinti="şase ucu işlemli")])
    kanit, vurgu = api._kanitlar(f)
    assert len(kanit) == 1 and kanit[0]["etiket"] == "Şase/podye/direk işlemi" and len(vurgu) == 1
