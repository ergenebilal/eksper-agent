"""R5.4 + R5.1 Belge röntgeni. ⚠ Belgeler SENTETİKTİR (gerçek rapor örnekleri gelene kadar; CyberOto_Arge.md R5.4 👤).
Doğrulanan: kişisel veri maskeleme, alıntısız/uydurma bulgunun atılması, ilanla kurallı karşılaştırma, teklif, hak, PDF."""
import base64

import pytest
from fastapi.testclient import TestClient

from arac_eksper.analysis import belge as bg
from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, api, security, xray_app
from tests.helpers import FakeLLM
from tests.test_xray_api import EXT, H, payload

RAPOR = """OTO EKSPERTIZ RAPORU (ornek)
Musteri: Ahmet Yilmaz
Plaka: 34 ABC 123   Sasi No: VF1RFB00X12345678
Telefon: 0532 111 22 33
Kilometre: 98.450
Kaporta: Motor kaputu boyali. Sag on camurluk degisen. Tavan orijinal. Sol on kapi lokal boyali.
Sase, podye ve direkler: islem yok, temiz.
Motor: Yag terlemesi mevcut. Debriyaj seti asinmis, degismeli.
Fren: On balatalar %20.
Tramer kaydi: 42.300 TL
"""

TRAMER = """Hasar kaydi sorgu sonucu
12.03.2021 tarihli kaza: 18.500 TL
04.11.2023 tarihli kaza: 27.250 TL
Toplam hasar tutari: 45.750 TL
Agir hasar kaydi bulunmamaktadir."""


def pdf(text: str) -> bytes:
    """Tek sayfalık, metin katmanlı en küçük PDF (ASCII)."""
    lines = text.splitlines()
    stream = "BT /F1 10 Tf 40 800 Td 12 TL " + " ".join(f"({l.replace('(', '').replace(')', '')}) '" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return out


class BelgeLLM(FakeLLM):
    """Gerçekçi çıktı + bilerek UYDURULMUŞ bulgular (alıntısı belgede yok / tutar belgede yok)."""
    def __init__(self):
        super().__init__()
        self.prompts = []

    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        self.prompts.append(user_prompt)
        if response_model is bg.EkspertizBulgular:
            return bg.EkspertizBulgular(
                rapor_km=98450, km_alinti="Kilometre: 98.450", tramer_tutari=42300, tramer_alinti="Tramer kaydi: 42.300 TL",
                yapisal="temiz", yapisal_alinti="Sase, podye ve direkler: islem yok, temiz",
                parcalar=[bg.BelgeParca(parca="motor_kaputu", durum="boyali", alinti="Motor kaputu boyali"),
                          bg.BelgeParca(parca="sag_on_camurluk", durum="degisen", alinti="Sag on camurluk degisen"),
                          bg.BelgeParca(parca="tavan", durum="orijinal", alinti="Tavan orijinal"),
                          bg.BelgeParca(parca="sol_on_kapi", durum="lokal_boyali", alinti="Sol on kapi lokal boyali"),
                          bg.BelgeParca(parca="bagaj_kapagi", durum="degisen", alinti="Bagaj kapagi degisen")],   # uydurma
                kusurlar=[bg.BelgeKusur(baslik="Motor yağ terlemesi", ciddiyet="orta", alinti="Yag terlemesi mevcut"),
                          bg.BelgeKusur(baslik="Debriyaj seti aşınmış", ciddiyet="yuksek", alinti="Debriyaj seti asinmis, degismeli"),
                          bg.BelgeKusur(baslik="Şanzıman arızası", ciddiyet="yuksek", alinti="Sanziman arizali")])      # uydurma
        if response_model is bg.TramerBulgular:
            return bg.TramerBulgular(
                kayitlar=[bg.TramerKayit(tarih="12.03.2021", tutar=18500, alinti="12.03.2021 tarihli kaza: 18.500 TL"),
                          bg.TramerKayit(tarih="04.11.2023", tutar=27250, alinti="04.11.2023 tarihli kaza: 27.250 TL"),
                          bg.TramerKayit(tarih="01.01.2024", tutar=99000, alinti="04.11.2023 tarihli kaza: 27.250 TL")],  # tutar uydurma
                toplam=45750, toplam_alinti="Toplam hasar tutari: 45.750 TL", agir_hasar="yok",
                agir_hasar_alinti="Agir hasar kaydi bulunmamaktadir")
        return super().parse_structured(system_prompt, user_prompt, response_model, model_name)


def test_masking_removes_personal_data_before_llm():
    m = bg.maskele(RAPOR)
    for s in ("Ahmet", "34 ABC 123", "VF1RFB00X12345678", "0532 111 22 33"):
        assert s not in m, s
    assert "Kilometre: 98.450" in m and "205/55 R16" in bg.maskele("Lastik 205/55 R16")


def test_invented_findings_are_dropped():
    b, atilan = bg.cikar(BelgeLLM(), "ekspertiz", bg.maskele(RAPOR))
    assert {p.parca for p in b.parcalar} == {"motor_kaputu", "sag_on_camurluk", "tavan", "sol_on_kapi"}
    assert [k.baslik for k in b.kusurlar] == ["Motor yağ terlemesi", "Debriyaj seti aşınmış"] and atilan == 2
    t, at2 = bg.cikar(BelgeLLM(), "tramer", TRAMER)
    assert [k.tutar for k in t.kayitlar] == [18500, 27250] and at2 == 1 and t.toplam == 45750


def test_comparison_offer_and_summary_are_rule_based():
    b, _ = bg.cikar(BelgeLLM(), "ekspertiz", bg.maskele(RAPOR))
    ilan = {"fiyat": 800_000, "km": 92_000, "parts": {"motor_kaputu": "orijinal", "sag_on_camurluk": "boyali",
                                                      "tavan": "orijinal"}, "tramer_beyan": 18_000}
    cel = bg.karsilastir("ekspertiz", b, ilan)
    msg = " ".join(c["mesaj"] for c in cel)
    assert "Motor kaputu: ilanda orijinal, raporda boyalı" in msg and "Sağ ön çamurluk: ilanda boyalı, raporda değişen" in msg
    assert "Sol ön kapı: ilanda belirtilmemiş" in msg and "98.450" in msg and "42.300" in msg and "Debriyaj" in msg
    assert all(c["alinti"] for c in cel)
    t = bg.teklif("ekspertiz", b, ilan, None, {"teklif": {"lokal_boyali": 0.01, "boyali": 0.02, "degisen": 0.04,
                                                           "tramer_payi": 0.5, "max_indirim": 0.15}})
    # 1 lokal (%1) + 1 boyalı (%2) + 1 değişen (%4) + tramer farkı 24.300/800.000*0,5 (%1,52) = %8,52 → 68.150 TL
    assert t["dusum"] == 68_150 and t["ust_sinir"] == 730_000
    assert "çelişiyor" in bg.ozet("ekspertiz", cel, b)


def test_pdf_text_layer_is_read_in_memory():
    raw = base64.b64encode(pdf(TRAMER)).decode()
    assert "Toplam hasar tutari: 45.750 TL" in bg.pdf_metni(raw)
    with pytest.raises(ValueError):
        bg.pdf_metni(base64.b64encode(b"GIF89a....").decode())


# ------------------------------------------------------------------ uç nokta
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "extension_token", EXT)
    security._fails.clear()
    api._calls.clear()
    llm = BelgeLLM()
    xray_app.app.dependency_overrides[api.get_llm] = lambda: llm
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        c.llm = llm
        yield c
    xray_app.app.dependency_overrides.clear()


def test_endpoint_tramer_pdf_vs_listing(client):
    ilan = payload(aciklama="Aracın tramer kaydı 18.000 TL. Ağır hasar kaydı yok.", agir_hasar_kayitli=False)
    r = client.post("/api/v1/belge", headers=H, json={"tur": "tramer", "pdf_b64": base64.b64encode(pdf(TRAMER)).decode(),
                                                      "ilan": ilan})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ilan_tramer_beyani"] == 18_000 and any("45.750" in c["mesaj"] for c in d["celiskiler"])
    assert d["teklif"]["ust_sinir"] < ilan["fiyat"] and d["dusen_bulgu"] == 1


def test_endpoint_member_pays_once_and_nothing_personal_reaches_llm(client):
    mid = accounts.create_member("b@ornek.com", gunluk_kota=5)
    h = {"Authorization": f"Bearer {accounts.issue_key(mid)}"}
    body = {"tur": "ekspertiz", "metin": RAPOR, "ilan": payload()}
    r = client.post("/api/v1/belge", headers=h, json=body)
    assert r.status_code == 200 and r.json()["hak_kullanildi"] is True and accounts.used_today(mid) == 1
    assert client.post("/api/v1/belge", headers=h, json=body).json()["hak_kullanildi"] is False
    assert accounts.used_today(mid) == 1
    assert not any(s in p for p in client.llm.prompts for s in ("Ahmet", "34 ABC 123", "0532"))


def test_endpoint_rejects_empty_or_bad_documents(client):
    assert client.post("/api/v1/belge", headers=H, json={"tur": "tramer", "metin": "kısa"}).status_code == 422
    bad = base64.b64encode(b"%PDF-1.4 bozuk").decode()
    assert client.post("/api/v1/belge", headers=H, json={"tur": "ekspertiz", "pdf_b64": bad}).status_code == 422
