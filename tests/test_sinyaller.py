"""R4.1 satış motivasyonu bandı + R4.2 ticari dil sinyali: alıntılı, olumsuzlamaya dayanıklı, dil kılavuzuna uygun."""
import re
from datetime import date, timedelta

from arac_eksper.analysis import sinyaller as sg

YASAK = re.compile(r"panik|fırsat|kelepir|dolandırıcı|sahtekar|alsatçı|çaresiz|kazık|enayi", re.I)
BUGUN = date(2026, 10, 7)


def test_text_and_data_reasons_give_a_band_with_quotes():
    t = "Yurt dışına taşınacağım için acil satılık. Ağır bakımı yapıldı."
    s = sg.satis_motivasyonu(t, BUGUN - timedelta(days=65), True, 20_000, bugun=BUGUN)
    assert s["bant"] == "yuksek" and s["indirim_ivmesi"] is True
    metin = [n for n in s["nedenler"] if n["kaynak"] == "metin"]
    assert {n["etiket"] for n in metin} >= {"Acil satış ifadesi", "Yurt dışına taşınma"}
    assert all(n["alinti"] and n["alinti"] in t for n in metin)              # birebir alıntı
    assert any("65 gündür" in n["etiket"] for n in s["nedenler"])


def test_negated_urgency_is_not_counted():
    for t in ("Acil değil, acelemiz yok. Gerçek alıcıya.", "Satış acelesi yoktur."):
        assert sg.satis_motivasyonu(t, bugun=BUGUN)["bant"] == "dusuk", t


def test_no_signal_means_low_band():
    s = sg.satis_motivasyonu("Bakımları zamanında yapıldı. Hatasız boyasız.", BUGUN - timedelta(days=3), False, bugun=BUGUN)
    assert s["bant"] == "dusuk" and s["nedenler"] == []


def test_commercial_language_signal_and_question():
    t = "Galerimizde kredi imkanı ile, takas değerlendirilir. Tüm araçlarımız ekspertizlidir."
    td = sg.ticari_dil(t, "Sahibinden")
    assert td["durum"] == "sinyal" and len(td["alintilar"]) >= 2 and all(a in t for a in td["alintilar"])
    q = sg.soru(td)
    assert q["oncelik"] == 1 and "fatura" in q["cevap_ise"].lower()
    assert sg.ticari_dil("Takas kabul edilir. Aracım temizdir.", "Sahibinden") is None    # tek ifade: sinyal değil
    d = sg.ticari_dil(t, "Galeriden")
    assert d["durum"] == "beyan" and sg.soru(d) is None


def test_language_guide():
    t = "Acil! Galerimizde kredi imkanı, senet ile taksit. Bugünlük fiyat, zararına."
    s, td = sg.satis_motivasyonu(t, BUGUN - timedelta(days=90), True, 5000, bugun=BUGUN), sg.ticari_dil(t, None)
    blob = " ".join([s["ad"]] + [n["etiket"] for n in s["nedenler"]] + [td["mesaj"], sg.soru(td)["soru"],
                                                                         sg.soru(td)["cevap_ise"]])
    assert not YASAK.search(blob)


def test_offer_effect_only_on_opening_and_from_rules():
    b = {"hedef": 800_000, "acilis": 770_000, "anlasma": 785_000, "ust_sinir": 800_000, "dayanak": []}
    rules = {"teklif": {"aciliyet_ek_orta": 0.01, "aciliyet_ek_yuksek": 0.02}}
    out = sg.teklife_uygula(dict(b, dayanak=[]), {"bant": "yuksek", "ad": "Hızlı satış motivasyonu: yüksek"}, rules)
    assert out["acilis"] == 750_000 and out["ust_sinir"] == 800_000 and out["acilis"] <= out["anlasma"] <= out["ust_sinir"]
    assert "açılış ek −%2" in out["dayanak"][-1]
    same = sg.teklife_uygula(dict(b, dayanak=[]), {"bant": "dusuk", "ad": "x"}, rules)
    assert same["acilis"] == 770_000


# ------------------------------------------------------------------ uç noktalar
def test_endpoints_return_signals_and_commercial_question(monkeypatch):
    from fastapi.testclient import TestClient

    from arac_eksper.config.settings import settings
    from arac_eksper.web import api, security, xray_app
    from tests.helpers import FakeLLM
    from tests.test_xray_api import EXT, H, payload
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    api._calls.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()
    acik = "Acil satılık. Galerimizde kredi imkanı vardır, takas değerlendirilir."
    p = payload(aciklama=acik, kimden="Sahibinden", fiyat_degisti=True, ilan_tarihi=(date.today() - timedelta(days=70)).isoformat())
    try:
        with TestClient(xray_app.app, base_url="http://panel.test") as c:
            q = c.post("/api/v1/quick", headers=H, json=p).json()
            assert q["sinyaller"]["satis"]["bant"] == "yuksek" and q["sinyaller"]["ticari"]["durum"] == "sinyal"
            assert any("Hızlı satış motivasyonu" in d for d in q["teklif"]["dayanak"])
            a = c.post("/api/v1/analyze", headers=H, json=p).json()
            assert any(s["kaynak"] == "ticari" for s in a["soru_carsafi"]) and a["sinyaller"]["ticari"]
    finally:
        xray_app.app.dependency_overrides.clear()
