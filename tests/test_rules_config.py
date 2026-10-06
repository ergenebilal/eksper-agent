import pytest
from datetime import datetime, timezone, date
from arac_eksper.schemas import ListingDetail, DescriptionFindings, PartState
from arac_eksper.analysis.rules_engine import determine_verdict, load_rules

def test_load_rules():
    rules = load_rules()
    assert "scoring" in rules
    assert rules["scoring"]["boyali_parca"] == -0.6

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
    # Kaput (painted) -> -0.6
    # Sol kapi (replaced) -> -1.2
    # Tramer: 20000 / 100000 = 0.20 > 0.10 -> tramer_10_plus -> -2.0
    # Total score = 10.0 - 0.6 - 1.2 - 2.0 = 6.2
    
    assert verdict.guven_skoru == 6.2


def test_moved_thresholds_keep_their_original_values():
    """Y1: kodda gömülü olan değerler yaml'a TAŞINDI, değişmedi. Bu test taşıma anındaki değerleri kilitler."""
    r = load_rules()
    assert r["bantlar"] == {"tramer_orani_alt": 0.05, "tramer_orani_ust": 0.10, "yillik_km_orta": 25000,
                            "yillik_km_yuksek": 35000, "yillik_km_suphe_alt": 4000, "yillik_km_suphe_min_yas": 5,
                            "sapma_bonus_alt": -0.15, "sapma_bonus_ust": -0.05, "sapma_ucuz_uyari": -0.20}
    assert r["tamlik"] == {"parca_yok": 0.3, "tramer_bilinmiyor": 0.1, "piyasa_yetersiz": 0.3}
    assert r["piyasa"] == {"gun": 30, "dar_km_payi": 0.30, "genis_km_payi": 0.50, "dar_min_n": 8}
    assert r["radar"]["fiyat_dusus_orani"] == 0.03
    assert r["teklif"]["lokal_boyali"] == 0.01 and r["teklif"]["degisen"] == 0.04 and r["teklif"]["max_indirim"] == 0.15


def test_engine_reads_bands_from_yaml(monkeypatch):
    import copy
    from arac_eksper.analysis import rules_engine
    from tests.test_hard_fails import _detail, _findings, MKT
    base = rules_engine.load_rules()
    d = _detail(fiyat=900000)
    f = _findings(tramer_tutari=60000)       # %6,7 → varsayılan bantta tramer_5_10
    assert any("Tramer" in t["kural"] and t["puan"] == -1.0 for t in determine_verdict(d, f, MKT).trace)
    changed = copy.deepcopy(base); changed["bantlar"]["tramer_orani_alt"] = 0.10
    monkeypatch.setattr(rules_engine, "load_rules", lambda: changed)
    assert any("Tramer" in t["kural"] and t["puan"] == -0.3 for t in determine_verdict(d, f, MKT).trace)
