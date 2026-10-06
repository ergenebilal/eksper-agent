"""Bilgi tabanları (R1.1 models_kb, R1.3 alim_gunu): şema, onay kuralı (kural 10), eşleşme, puan ve liste etkisi."""
from datetime import datetime, timezone

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.analysis import models_kb, rehber, rules_engine
from arac_eksper.config.settings import settings
from arac_eksper.schemas import DescriptionFindings, ListingDetail, MarketStats
from arac_eksper.web import api, security, xray_app
from tests.helpers import FakeLLM
from tests.test_xray_api import EXT, H

runner = CliRunner()


def car(**kw):
    d = dict(ilan_no="1", url="", baslik="Temiz araç", marka="Renault", model="Megane", seri="Megane",
             paket="1.5 dCi Touch EDC", vites="Otomatik", yakit="Dizel", fiyat=800_000, yil=2018, km=130_000,
             il="Bursa", ilan_tarihi=datetime.now().date(), aciklama="", fetched_at=datetime.now(timezone.utc),
             parts={"tavan": "orijinal"})
    d.update(kw)
    return ListingDetail(**d)


KB = [{
    "marka": "Renault", "model": "Mégane", "yil_min": 2012, "yil_max": 2023, "onayli": True, "kaynak": "test",
    "kronik": [
        {"etiket": "EDC kavrama", "kontrol": "kalkış titremesi", "motor": ["EDC"], "vites": "otomatik",
         "km_esik": 100000, "ciddiyet": "yuksek"},
        {"etiket": "DPF", "kontrol": "DPF hata kaydı", "motor": ["1.5 dCi"], "km_esik": 150000, "ciddiyet": "orta"},
        {"etiket": "Eski kasa sorunu", "kontrol": "x", "yil_max": 2014, "ciddiyet": "yuksek"},
    ],
    "bakim": [{"kalem": "Triger seti", "motor": ["1.5 dCi"], "aralik_km": [120000, 160000], "not": "Kayışlı"}],
}]


# ------------------------------------------------------------------ bilgi tabanı dosyası
def test_kb_file_is_valid_and_every_entry_has_source_and_approval_flag():
    tum = models_kb.load_kb(include_unapproved=True)
    assert len(tum) >= 30 and models_kb.validate(tum) == []
    assert all(e.get("kaynak") and isinstance(e.get("onayli"), bool) for e in tum)
    assert all("Onay:" in e["kaynak"] for e in tum if e["onayli"])   # onayın kaynağı izlenebilir


def _unapproved_copy(tmp_path):
    p = tmp_path / "kb.yaml"
    src = yaml.safe_load(models_kb.KB_PATH.read_text(encoding="utf-8"))
    for e in src["models"]:
        e["onayli"] = False
    p.write_text(yaml.safe_dump(src, allow_unicode=True), encoding="utf-8")
    return p


def test_unapproved_entries_are_never_loaded_and_change_no_verdict(tmp_path):
    p = _unapproved_copy(tmp_path)
    assert models_kb.load_kb(path=p) == [] and len(models_kb.load_kb(include_unapproved=True, path=p)) >= 30
    d = car()
    f = DescriptionFindings(sase_direk_podye_islem="yok_beyan", airbag="orijinal_beyan", motor_sanziman="belirsiz",
                            km_degisimi_suphesi=False)
    m = MarketStats(n=10, medyan=900_000, p25=850_000, p75=950_000, guven="yuksek")
    assert (rules_engine.determine_verdict(d, f, m, kb=models_kb.load_kb(path=p)).guven_skoru
            == rules_engine.determine_verdict(d, f, m, kb=[]).guven_skoru)


def test_validate_reports_bad_entries():
    bad = [{"marka": "X", "model": "Y", "onayli": "evet", "kronik": [{"etiket": "a", "ciddiyet": "çok"}],
            "bakim": [{"kalem": "k", "aralik_km": [200, 100]}]}]
    errs = " | ".join(models_kb.validate(bad))
    for frag in ("kaynak", "onayli", "kontrol", "ciddiyet", "aralik_km"):
        assert frag in errs


# ------------------------------------------------------------------ eşleşme
def test_matching_uses_folded_names_engine_gearbox_and_item_years():
    names = {k["etiket"] for k in models_kb.kronik_arizalar(car(), KB)}
    assert names == {"EDC kavrama", "DPF"}                            # "Mégane" = "Megane"; 2018 > item yil_max 2014
    assert "EDC kavrama" not in {k["etiket"] for k in models_kb.kronik_arizalar(car(vites="Manuel", paket="1.5 dCi Touch"), KB)}
    assert models_kb.kronik_arizalar(car(model="Clio", seri="Clio"), KB) == []
    assert models_kb.kronik_arizalar(car(yil=2010), KB) == []
    assert "Eski kasa sorunu" in {k["etiket"] for k in models_kb.kronik_arizalar(car(yil=2013), KB)}


def test_km_threshold_marks_items_triggered_and_orders_them_first():
    k = models_kb.kronik_arizalar(car(km=130_000), KB)
    assert [(x["etiket"], x["tetiklendi"]) for x in k] == [("EDC kavrama", True), ("DPF", False)]
    k = models_kb.kronik_arizalar(car(km=60_000), KB)
    assert all(not x["tetiklendi"] for x in k)


def test_maintenance_items_only_when_km_reaches_interval():
    assert models_kb.bakim_kalemleri(car(km=100_000), KB) == []
    assert models_kb.bakim_kalemleri(car(km=125_000), KB)[0]["kalem"] == "Triger seti"


def test_checklist_is_specific_and_prioritised():
    m = models_kb.ekspertiz_maddeleri(car(km=130_000), KB)
    assert m[0].startswith("EDC kavrama") and "130.000 km" in m[0]
    assert m[1].startswith("Triger seti: 120.000-160.000 km") and "faturasını" in m[1]
    assert m[2].startswith("DPF")                                    # tetiklenmemiş en sonda


def test_only_high_severity_triggered_items_cost_points():
    f = DescriptionFindings(sase_direk_podye_islem="yok_beyan", airbag="orijinal_beyan", motor_sanziman="belirsiz",
                            km_degisimi_suphesi=False)
    m = MarketStats(n=10, medyan=900_000, p25=850_000, p75=950_000, guven="yuksek")
    base = rules_engine.determine_verdict(car(km=130_000), f, m, kb=[])
    with_kb = rules_engine.determine_verdict(car(km=130_000), f, m, kb=KB)
    low_km = rules_engine.determine_verdict(car(km=60_000), f, m, kb=KB)
    pen = rules_engine.load_rules()["scoring"]["kronik_ariza"]       # yalnız EDC (yüksek + tetik) bir kez düşer
    assert round(base.guven_skoru - with_kb.guven_skoru, 1) == round(abs(pen), 1) > 0
    assert low_km.guven_skoru == rules_engine.determine_verdict(car(km=60_000), f, m, kb=[]).guven_skoru
    assert any("EDC kavrama" in x for x in with_kb.ekspertiz_kontrol_listesi)
    assert "Kronik arıza riski: EDC kavrama" in with_kb.eksiler and not any("DPF" in e for e in with_kb.eksiler)


# ------------------------------------------------------------------ alım günü rehberi
def test_alim_gunu_valid_and_hidden_when_unapproved(tmp_path):
    assert rehber.validate_alim_gunu() == []
    d = rehber.load_alim_gunu(include_unapproved=True)
    assert len(d["bolumler"]) >= 4 and "hukuki tavsiye değildir" in d["uyari"]
    src = yaml.safe_load(rehber.ALIM_GUNU_PATH.read_text(encoding="utf-8"))
    src["onayli"] = False
    p = tmp_path / "alim.yaml"
    p.write_text(yaml.safe_dump(src, allow_unicode=True), encoding="utf-8")
    assert rehber.load_alim_gunu(path=p) is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        yield c
    xray_app.app.dependency_overrides.clear()


def test_rehber_endpoint_serves_only_approved_content(client, tmp_path, monkeypatch):
    for onay in (True, False):
        src = yaml.safe_load(rehber.ALIM_GUNU_PATH.read_text(encoding="utf-8"))
        src["onayli"] = onay
        p = tmp_path / f"alim_{onay}.yaml"
        p.write_text(yaml.safe_dump(src, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(rehber.load_alim_gunu, "__defaults__", (False, p))
        d = client.get("/api/v1/rehber", headers=H).json()["alim_gunu"]
        assert (d is not None and bool(d["bolumler"][0]["maddeler"])) if onay else d is None
    assert client.get("/api/v1/rehber").status_code == 401


def test_cli_kb_kontrol():
    r = runner.invoke(cli.app, ["kb", "kontrol"])
    assert r.exit_code == 0, r.output
    assert "Şema geçerli" in r.output and ("onaylı (panelde görünür)" in r.output or "taslak (panelde görünmez)" in r.output)
