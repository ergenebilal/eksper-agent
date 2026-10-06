import pytest
from datetime import datetime, timezone, date
from arac_eksper.schemas import ListingDetail, DescriptionFindings, PartState
from arac_eksper.analysis.rules_engine import determine_verdict, load_rules

def test_load_rules():
    rules = load_rules()
    assert "scoring" in rules
    assert rules["scoring"]["boyali_parca"] == -0.5

def test_rules_engine_scoring_with_yaml():
    detail = ListingDetail(
        ilan_no="1", url="", baslik="", marka="", model="",
        fiyat=100000, yil=2020, km=50000, il="", ilan_tarihi=date.today(),
        parts={"kaput": PartState.PAINTED, "sol_kapi": PartState.REPLACED},
        aciklama="", fetched_at=datetime.now(timezone.utc)
    )
    findings = DescriptionFindings(
        sase_direk_podye_islem="yok_beyan",
        airbag="orijinal_beyan",
        motor_sanziman="belirsiz",
        km_degisimi_suphesi=False,
        tramer_tutari=20000,
        tramer_sayisi=1,
        dolandiricilik_sinyalleri=[],
        olumlu_sinyaller=[],
        olumsuz_sinyaller=[],
        belirsiz_ifadeler=[],
        ekspertiz_durumu_guvenilir=True
    )
    
    verdict = determine_verdict(detail, findings, market=None)
    
    # Base: 10.0
    # Kaput (painted) -> -0.5
    # Sol kapi (replaced) -> -1.0
    # Tramer: 20000 / 100000 = 0.20 > 0.10 -> tramer_10_plus -> -2.0
    # Total score = 10.0 - 0.5 - 1.0 - 2.0 = 6.5
    
    assert verdict.guven_skoru == 6.5
