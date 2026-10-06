"""R3.3 Savaş Odası karşılaştırması: kurallı seçimler, doğrulanmış anlatım, hak ve röntgen önkoşulu."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from arac_eksper.analysis import compare as cmp
from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, api, security, xray_app
from tests.helpers import FakeLLM
from tests.test_xray_api import EXT, H, payload


def item(no, fiyat=800_000, etiket="DUSUNULEBILIR", skor=7.0, hard=(), gun=10, degisti=False, sapma=0.0, acik="Araç temiz."):
    return {"ilan_no": no, "baslik": f"İlan {no}", "fiyat": fiyat, "yil": 2018, "km": 100_000, "marka": "Renault",
            "seri": "Megane", "aciklama": acik, "ilan_tarihi": (date(2026, 10, 7) - timedelta(days=gun)).isoformat(),
            "fiyat_degisti": degisti, "sonuc": {"etiket": etiket, "skor": skor, "veri_tamlik": 0.8, "hard_fails": list(hard),
            "eksiler": list(hard), "artilar": ["İlk sahibinden"], "sapma_yuzde": sapma}}


def tablo_of(items):
    from arac_eksper.web.api import CompareItem
    return [cmp.satir(n, dict(CompareItem(**i).model_dump(), gercek_maliyet=None), date(2026, 10, 7))
            for n, i in enumerate(items, 1)]


def test_picks_are_rule_based_and_explainable():
    t = tablo_of([item("A", skor=8.2, etiket="ALINIR", fiyat=850_000), item("B", skor=8.2, etiket="ALINIR", fiyat=820_000),
                  item("C", etiket="ALINMAZ", skor=9.0, hard=["Tavan boyali"]), item("D", gun=60, degisti=True, sapma=12.0)])
    s = cmp.secimler(t)
    assert s["galip"] == "B"                       # aynı etiket ve puanda daha düşük toplam maliyet
    assert s["en_riskli"] == "C"                   # elenme nedeni
    assert s["pazarlik"] == "D"                    # 60 gün + fiyat değişti + piyasa üstü
    assert s["ekspertiz_sirasi"] == ["B", "A", "D"] and "C" not in s["ekspertiz_sirasi"]


def test_all_eliminated_still_returns_a_choice():
    s = cmp.secimler(tablo_of([item("A", etiket="ALINMAZ", hard=["x"]), item("B", etiket="ALINMAZ", hard=["y"], skor=5)]))
    assert s["galip"] in ("A", "B") and s["ekspertiz_sirasi"] == []


def test_narrative_validation_drops_invented_numbers_and_banned_words():
    t = tablo_of([item("A", fiyat=850_000), item("B", fiyat=820_000)])
    txt = ("2 numaralı ilan 820.000 TL ile öne çıkıyor. Ayrıca 45.000 TL masraf çıkabilir. "
           "1 numaralı ilan tam bir fırsat. 1 numaralı ilanın puanı 7.0/10.")
    out = cmp.dogrula(txt, t)
    assert "820.000" in out and "45.000" not in out and "fırsat" not in out and "7.0/10" in out


def test_template_uses_only_table_numbers():
    t = tablo_of([item("A", gun=30, degisti=True, sapma=5.0), item("B", etiket="ALINMAZ", hard=["Tavan boyali"])])
    a = cmp.sablon_anlatim(t, cmp.secimler(t))
    assert all(cmp.dogrula(v, t) == v for v in a.values())
    assert "Tavan boyali" in a["en_riskli"] and "30 gündür yayında" in a["pazarlik"]


# ------------------------------------------------------------------ uç nokta
class CompareLLM(FakeLLM):
    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        if response_model is cmp.Anlatim:
            return cmp.Anlatim(galip="2 numaralı ilan öne çıkıyor. Toplam 99.999 TL tasarruf sağlar.",
                               en_riskli="1 numaralı ilan daha riskli.", pazarlik="1 numaralı ilanda pazarlık payı var.")
        return super().parse_structured(system_prompt, user_prompt, response_model, model_name)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    api._calls.clear()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: CompareLLM()
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        yield c
    xray_app.app.dependency_overrides.clear()


def test_owner_compare_with_validated_llm_text(client):
    r = client.post("/api/v1/compare", headers=H, json={"ilanlar": [item("A"), item("B", fiyat=700_000)]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["llm"] is True and "99.999" not in d["anlatim"]["galip"] and "2 numaralı ilan" in d["anlatim"]["galip"]
    assert len(d["tablo"]) == 2 and d["galip"] in ("A", "B") and d["yasal_uyari"]


def test_member_needs_xray_first_then_pays_once_per_set(client):
    mid = accounts.create_member("k@ornek.com", gunluk_kota=10)
    h = {"Authorization": f"Bearer {accounts.issue_key(mid)}"}
    a, b = item("1001", acik="Araç ilk sahibinden. Tramer kaydı yoktur."), item("1002", acik="Araç temiz.")
    r = client.post("/api/v1/compare", headers=h, json={"ilanlar": [a, b]})
    assert r.status_code == 409 and "1 numaralı" in r.json()["detail"]
    for x in (a, b):                                                    # tekil röntgenler (2 hak)
        assert client.post("/api/v1/analyze", headers=h, json=payload(ilan_no=x["ilan_no"], aciklama=x["aciklama"])).status_code == 200
    r = client.post("/api/v1/compare", headers=h, json={"ilanlar": [a, b]})
    assert r.status_code == 200 and r.json()["hak_kullanildi"] is True and accounts.used_today(mid) == 3
    r = client.post("/api/v1/compare", headers=h, json={"ilanlar": [b, a]})   # aynı küme, sıra farklı: ücretsiz
    assert r.json()["hak_kullanildi"] is False and accounts.used_today(mid) == 3


def test_compare_validation(client):
    assert client.post("/api/v1/compare", headers=H, json={"ilanlar": [item("A")]}).status_code == 422
    assert client.post("/api/v1/compare", headers=H, json={"ilanlar": [item("A"), item("A")]}).status_code == 422
    assert client.post("/api/v1/compare", headers=H, json={"ilanlar": [item(str(i)) for i in range(6)]}).status_code == 422
    assert client.post("/api/v1/compare", json={"ilanlar": [item("A"), item("B")]}).status_code == 401


def test_llm_failure_falls_back_to_template(client):
    xray_app.app.dependency_overrides[api.get_llm] = lambda: FakeLLM()          # Anlatim üretemez
    d = client.post("/api/v1/compare", headers=H, json={"ilanlar": [item("A"), item("B")]}).json()
    assert d["llm"] is False and "numaralı ilan" in d["anlatim"]["galip"]
