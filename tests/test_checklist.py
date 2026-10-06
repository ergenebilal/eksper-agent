"""R1.2 araca özel ekspertiz listesi + R1.4 satıcıya sorulacaklar (soru çarşafı). LLM'siz, deterministik."""
import re
from datetime import datetime, timezone

from arac_eksper.analysis.checklist import ekspertiz_bolumleri, soru_carsafi, soru_metni
from arac_eksper.schemas import DescriptionFindings, Evidence, ListingDetail, MarketStats

TUM = ["on_tampon", "arka_tampon", "motor_kaputu", "bagaj_kapagi", "tavan", "sol_on_camurluk", "sag_on_camurluk",
       "sol_arka_camurluk", "sag_arka_camurluk", "sol_on_kapi", "sag_on_kapi", "sol_arka_kapi", "sag_arka_kapi"]
KB = [{"marka": "Renault", "model": "Megane", "yil_min": 2012, "yil_max": 2023, "onayli": True, "kaynak": "t",
       "kronik": [{"etiket": "EDC kavrama", "kontrol": "kalkış titremesi", "vites": "otomatik", "km_esik": 100000, "ciddiyet": "yuksek"}],
       "bakim": [{"kalem": "Triger seti", "motor": ["1.5 dCi"], "aralik_km": [120000, 160000]}]}]
YASAK = re.compile(r"panik|fırsat|kelepir|dolandırıcı|sahtekar|alsatçı|çaresiz|kap\b", re.I)


def car(**kw):
    d = dict(ilan_no="1", url="", baslik="", marka="Renault", model="Megane", seri="Megane", paket="1.5 dCi Touch",
             vites="Otomatik", yakit="Dizel", fiyat=800_000, yil=2016, km=130_000, il="", aciklama="",
             ilan_tarihi=datetime.now().date(), fetched_at=datetime.now(timezone.utc), parts={p: "orijinal" for p in TUM})
    d.update(kw)
    return ListingDetail(**d)


def bulgu(**kw):
    d = dict(sase_direk_podye_islem="belirsiz", airbag="belirsiz", motor_sanziman="belirsiz", km_degisimi_suphesi=False)
    d.update(kw)
    return DescriptionFindings(**d)


def test_data_gaps_become_priority_one_questions():
    q = soru_carsafi(car(parts={}), bulgu())
    assert [x["oncelik"] for x in q] == sorted(x["oncelik"] for x in q)
    texts = " ".join(x["soru"] for x in q)
    for frag in ("boyalı ya da değişen", "Şase uçları", "Airbag", "tramer"):
        assert frag in texts
    assert all(x["neden"] and x["cevap_ise"] and x["kaynak"] for x in q)


def test_known_facts_do_not_produce_questions():
    q = soru_carsafi(car(), bulgu(sase_direk_podye_islem="yok_beyan", airbag="orijinal_beyan", tramer_tutari=0))
    texts = " ".join(x["soru"] for x in q)
    assert "Şase" not in texts and "Airbag" not in texts and "tramer" not in texts and "boyalı ya da değişen" not in texts


def test_vague_phrases_are_quoted_in_questions_and_checklist():
    f = bulgu(belirsiz_ifadeler=[Evidence(etiket="kaçamak", alinti="ufak tefek masrafı var")])
    assert any("“ufak tefek masrafı var”" in x["soru"] for x in soru_carsafi(car(), f))
    assert any("ufak tefek masrafı var" in x["madde"] and x["kaynak"] == "bulgu"
               for x in ekspertiz_bolumleri(car(), f)["bu_aracta"])


def test_kb_maintenance_and_triggered_chronic_feed_both_lists():
    b = ekspertiz_bolumleri(car(), bulgu(), KB)["bu_aracta"]
    assert any(x["kaynak"] == "kronik" and x["madde"].startswith("EDC kavrama") for x in b)
    assert any(x["kaynak"] == "bakim" and x["madde"].startswith("Triger seti") for x in b)
    q = soru_carsafi(car(), bulgu(tramer_tutari=0), kb=KB)
    assert any(x["kaynak"] == "bakim" and "Triger seti yapıldı mı" in x["soru"] for x in q)
    assert any(x["kaynak"] == "kronik" and "EDC kavrama" in x["soru"] for x in q)


def test_findings_create_specific_checks():
    f = bulgu(sase_direk_podye_islem="var", airbag="acmis", motor_sanziman="sorunlu", km_degisimi_suphesi=True, tramer_tutari=45000)
    m = " ".join(x["madde"] for x in ekspertiz_bolumleri(car(parts={"sag_on_camurluk": "degisen"}), f)["bu_aracta"])
    for frag in ("Şase ölçümü", "Airbag sistem", "kompresyon", "Kilometre doğrulaması", "45.000 TL", "sağ ön çamurluk"):
        assert frag in m


def test_diagram_warning_and_declared_original_lead_the_checklist():
    b = ekspertiz_bolumleri(car(parts={}), bulgu(), sema_uyari="çelişki")["bu_aracta"]
    assert b[0]["kaynak"] == "sema" and "çelişiyor" in b[0]["madde"]
    b = ekspertiz_bolumleri(car(), bulgu(), beyan_orijinal=True)["bu_aracta"]
    assert b[0]["kaynak"] == "sema" and "satıcı beyanıdır" in b[0]["madde"]


def test_negotiation_questions_from_market():
    m = MarketStats(n=12, medyan=1_000_000, p25=900_000, p75=1_100_000, guven="yuksek")
    assert any("pazarlık payı" in x["soru"] for x in soru_carsafi(car(), bulgu(), m, sapma=0.12))
    assert any("nedeni nedir" in x["soru"] for x in soru_carsafi(car(), bulgu(), m, sapma=-0.30))
    assert not any(x["kaynak"] == "piyasa" for x in soru_carsafi(car(), bulgu(), MarketStats(n=2, medyan=1, p25=1, p75=1, guven="dusuk"), sapma=0.3))


def test_language_guide_and_limits():
    f = bulgu(belirsiz_ifadeler=[Evidence(etiket="x", alinti="a"), Evidence(etiket="y", alinti="b")], km_degisimi_suphesi=True)
    m = MarketStats(n=12, medyan=1_000_000, p25=900_000, p75=1_100_000, guven="yuksek")
    q = soru_carsafi(car(parts={}, km=200_000), f, m, KB, "çelişki", -0.3)
    b = ekspertiz_bolumleri(car(parts={}, km=200_000), f, KB, "çelişki")
    blob = " ".join(str(v) for x in q for v in x.values()) + " ".join(x["madde"] for x in b["bu_aracta"])
    assert not YASAK.search(blob)
    assert len(q) <= 10
    assert soru_metni(q).startswith("1. ") and soru_metni(q).count("\n") == len(q) - 1
