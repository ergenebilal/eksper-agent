"""R2.2 + R2.3 gerçek maliyet: kural tabanlı masraf bulma (alıntılı), olası bakım, onaylı tutar, teklif düşümü."""
from datetime import datetime, timezone

import pytest

from arac_eksper.analysis import masraf, masraf_kb
from arac_eksper.schemas import ListingDetail

TUM = masraf_kb.kalemler(include_unapproved=True)
ONAYLI = {k: dict(v, onayli=True) for k, v in TUM.items()}           # onay simülasyonu
KB = [{"marka": "Renault", "model": "Megane", "onayli": True, "kaynak": "t",
       "bakim": [{"kalem": "Triger seti", "motor": ["1.5 dCi"], "aralik_km": [120000, 160000], "masraf": "triger_seti"}]}]


@pytest.mark.parametrize("metin,kod", [
    ("sadece baski balatasi deyislecek ondada fiyada indrim olcak", "debriyaj_seti"),     # yazım hatalı, gerçek ilan
    ("İKİNCİ VİTESTEN ATIYOR SEKROMENCİ YAPILACAK", "senkromec"),
    ("İKİ ARKA SAĞ AMASOR DEĞİŞECEK SES YAPIYOR", "amortisor_cift"),
    ("klimaya gaz basılacak", "klima_gaz"),
    ("lastikleri bitik", "lastik_takim"),
    ("triger seti zamanı gelmiş", "triger_seti"),
    ("ön camda çatlak var değişmeli", "on_cam"),
])
def test_needed_work_is_found_with_a_verbatim_quote(metin, kod):
    r = masraf.metinden_masraflar(metin, TUM)
    assert [x["kod"] for x in r] == [kod]
    assert r[0]["alinti"] in metin


@pytest.mark.parametrize("metin", [
    "Turbo ve enjektörler sıfırdır. Lastikleri 9 ay önce sıfır alınmış olup, yeni durumdadır.",
    "devirdaim termostat değiştirildi",
    "yağı filtreleri değişmiştir 4 lastik yeni",
    "DUMAN ATMA VE UFACIK YAĞ KAÇAĞI YOKTUR",
    "KLİMA AKTİF ÇALIŞIYOR",
    "Far değişiminden dolayı 50 bin tl tramer mevcut",
    "ön takım alt takım vs yeni yapılmıştır",
    "ağır bakımı yapıldı darbe boya hata yok",
])
def test_done_negated_or_past_work_is_not_a_cost(metin):
    assert masraf.metinden_masraflar(metin, TUM) == []


def test_specific_phrase_wins_over_generic_one():
    r = masraf.metinden_masraflar("baskı balatası değişecek", TUM)
    assert [x["kod"] for x in r] == ["debriyaj_seti"]                      # fren balatası sayılmaz


def car(**kw):
    d = dict(ilan_no="1", url="", baslik="", marka="Renault", model="Megane", seri="Megane", paket="1.5 dCi Touch",
             vites="Otomatik", yakit="Dizel", fiyat=800_000, yil=2016, km=130_000, il="", aciklama="",
             ilan_tarihi=datetime.now().date(), fetched_at=datetime.now(timezone.utc))
    d.update(kw)
    return ListingDetail(**d)


def test_due_maintenance_is_possible_unless_text_says_done():
    gm = masraf.gercek_maliyet(car(), ONAYLI, TUM, KB)
    assert [(k["kod"], k["kesinlik"]) for k in gm["kalemler"]] == [("triger_seti", "olasi")]
    assert masraf.gercek_maliyet(car(aciklama="Triger seti yapıldı, faturası var."), ONAYLI, TUM, KB) is None
    assert masraf.gercek_maliyet(car(aciklama="Ağır bakımı yapıldı."), ONAYLI, TUM, KB) is None
    assert masraf.gercek_maliyet(car(km=90_000), ONAYLI, TUM, KB) is None


def test_totals_use_approved_ranges_only():
    d = car(aciklama="klimaya gaz basılacak, lastikleri bitik")
    gm = masraf.gercek_maliyet(d, ONAYLI, TUM, KB, seg="orta")
    lo = sum(ONAYLI[k]["aralik"]["orta"][0] for k in ("klima_gaz", "lastik_takim"))
    hi = sum(ONAYLI[k]["aralik"]["orta"][1] for k in ("klima_gaz", "lastik_takim", "triger_seti"))
    assert gm["beyan_alt"] == lo and gm["toplam_alt"] == 800_000 + lo and gm["toplam_ust"] == 800_000 + hi
    taslak = masraf.gercek_maliyet(d, {}, TUM, KB, seg="orta")                # hiçbir kalem onaylı değil
    assert taslak["tutarsiz_kalem"] == 3 and taslak["beyan_alt"] == 0 and all(k["aralik"] is None for k in taslak["kalemler"])


def test_offer_reduced_by_declared_costs_only_and_order_kept():
    b = {"hedef": 700_000, "acilis": 650_000, "anlasma": 675_000, "ust_sinir": 700_000, "dayanak": []}
    gm = {"beyan_alt": 23_500, "kalemler": [{"kesinlik": "beyan", "aralik": [23_500, 40_000]}]}
    r = masraf.teklife_uygula(dict(b, dayanak=[]), gm)
    assert (r["acilis"], r["anlasma"], r["ust_sinir"]) == (625_000, 650_000, 675_000)
    assert r["acilis"] <= r["anlasma"] <= r["ust_sinir"] and "23.500 TL" in r["dayanak"][-1]
    assert masraf.teklife_uygula(dict(b, dayanak=[]), {"beyan_alt": 0, "kalemler": []})["acilis"] == 650_000
    assert masraf.teklife_uygula(None, gm) is None


# ------------------------------------------------------------------ R2.2b: LLM kalemleri
def test_llm_cost_items_are_validated_and_merged():
    from arac_eksper.analysis.description_llm import _masraf_dogrula, _match_key
    from arac_eksper.schemas import MasrafEvidence
    text = "Klimanın gazı bitti, doldurulması lazım. Triger seti yapıldı. Ön fren balataları da yakında."
    key = _match_key(text)
    items = [MasrafEvidence(kod="klima_gaz", alinti="Klimanın gazı bitti"),          # geçerli
             MasrafEvidence(kod="triger_seti", alinti="Triger seti yapıldı"),        # yapılmış: atılır
             MasrafEvidence(kod="uydurma_kod", alinti="Ön fren balataları"),         # KB'de yok: atılır
             MasrafEvidence(kod="fren_on", alinti="ön balatalar bitik")]             # metinde yok: atılır
    out = _masraf_dogrula(items, key)
    assert [m.kod for m in out] == ["klima_gaz"]
