import pytest
from datetime import datetime, timezone, date
from arac_eksper.analysis.rules_engine import determine_verdict
from arac_eksper.schemas import ListingDetail, DescriptionFindings, MarketStats

def test_verdict_without_market():
    # Mükemmel bir ilan, normalde ALINIR olmalı ama piyasa verisi n=0
    detail = ListingDetail(
        ilan_no="PERFECT_1", url="url", baslik="Temiz Araç",
        marka="Renault", model="Megane",
        fiyat=100000, yil=2020, km=30000, il="İstanbul", ilan_tarihi=date.today(),
        parts={"kaput": "orijinal", "tavan": "orijinal"},
        aciklama="Temiz", fetched_at=datetime.now(timezone.utc)
    )
    
    findings = DescriptionFindings(
        sase_direk_podye_islem="yok_beyan",
        airbag="orijinal_beyan",
        motor_sanziman="belirsiz",
        km_degisimi_suphesi=False,
        tramer_tutari=0,
        tramer_sayisi=0,
        dolandiricilik_sinyalleri=[],
        olumlu_sinyaller=[],
        olumsuz_sinyaller=[],
        belirsiz_ifadeler=[],
        ekspertiz_durumu_guvenilir=True
    )
    
    market = MarketStats(n=4, medyan=100000, p25=95000, p75=105000, guven="yok")
    
    verdict = determine_verdict(detail, findings, market)
    
    # ALINIR olmamalı, çünkü n<5
    assert verdict.etiket == "DUSUNULEBILIR"
    assert verdict.veri_tamlik < 0.8  # Çünkü 1.0 - 0.3 = 0.7 olmalı (tamlik = 0.7)
