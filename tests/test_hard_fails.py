from datetime import datetime, timezone, date
from arac_eksper.analysis.rules_engine import determine_verdict, load_rules
from arac_eksper.schemas import ListingDetail, DescriptionFindings, MarketStats, PartState, Evidence

def _detail(**kw):
    base = dict(ilan_no="1", url="", baslik="b", marka="Renault", model="Megane", fiyat=845000, yil=2022, km=60000,
                il="Bursa", ilan_tarihi=date.today(), parts={"tavan": PartState.ORIGINAL, "kaput": PartState.ORIGINAL},
                aciklama="", fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc))
    base.update(kw)
    return ListingDetail(**base)

def _findings(**kw):
    base = dict(sase_direk_podye_islem="yok_beyan", airbag="orijinal_beyan", motor_sanziman="sorunsuz_beyan",
                km_degisimi_suphesi=False, tramer_tutari=0)
    base.update(kw)
    return DescriptionFindings(**base)

MKT = MarketStats(n=20, medyan=900000, p25=880000, p75=920000, guven="yuksek")

def test_yaml_has_thresholds():
    hf = load_rules()["hard_fails"]
    assert hf["max_sapma"] == 0.25 and hf["max_yillik_km"] == 45000 and hf["dolandiricilik_sapma"] == -0.20

def test_budget_hard_fail():
    v = determine_verdict(_detail(fiyat=900000), _findings(), MKT, max_butce=850000)
    assert v.etiket == "ALINMAZ" and any("bütçe" in f for f in v.hard_fails)

def test_within_budget_no_fail():
    v = determine_verdict(_detail(), _findings(), MKT, max_butce=900000)
    assert not any("bütçe" in f for f in v.hard_fails)

def test_tavan_local_paint_is_hard_fail():
    v = determine_verdict(_detail(parts={"tavan": PartState.LOCAL_PAINT}), _findings(), MKT)
    assert v.etiket == "ALINMAZ" and any("Tavan" in f for f in v.hard_fails)

def test_price_over_market_hard_fail():
    v = determine_verdict(_detail(fiyat=1_200_000), _findings(), MKT)
    assert any("piyasanın" in f for f in v.hard_fails) and v.etiket == "ALINMAZ"

def test_high_yearly_km_hard_fail():
    v = determine_verdict(_detail(yil=2024, km=200000), _findings(), MKT)
    assert any("Yıllık KM" in f for f in v.hard_fails)

def test_sase_and_airbag_hard_fail():
    v = determine_verdict(_detail(), _findings(sase_direk_podye_islem="var", airbag="acmis"), MKT)
    assert len(v.hard_fails) >= 2 and v.etiket == "ALINMAZ"

def test_fraud_and_too_cheap_hard_fail():
    f = _findings(dolandiricilik_sinyalleri=[Evidence(etiket="kapora", alinti="kapora")])
    v = determine_verdict(_detail(fiyat=650000), f, MKT)
    assert any("Dolandırıcılık" in x for x in v.hard_fails)

def test_tramer_zero_is_not_penalized_unknown_is():
    # fiyat = medyan -> fiyat avantajı bonusu yok, skor 10'da kırpılmaz
    a = determine_verdict(_detail(fiyat=900000), _findings(tramer_tutari=0), MKT)
    b = determine_verdict(_detail(fiyat=900000), _findings(tramer_tutari=None), MKT)
    assert round(a.guven_skoru - b.guven_skoru, 1) == 0.5   # tramer_bilinmiyor = -0.5
    assert a.veri_tamlik > b.veri_tamlik

def test_good_listing_with_market_is_alinir():
    f = _findings(olumlu_sinyaller=[Evidence(etiket="ilk sahibinden", alinti="x")] * 2)
    v = determine_verdict(_detail(fiyat=820000), f, MKT, max_butce=900000)
    assert v.etiket == "ALINIR", (v.etiket, v.guven_skoru, v.hard_fails)
