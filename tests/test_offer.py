import pytest
from datetime import datetime, timezone, date
from arac_eksper.schemas import ListingDetail, DescriptionFindings, Verdict, MarketStats
from arac_eksper.analysis.offer import calculate_offer

def get_base_findings():
    return DescriptionFindings(
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

def test_offer_ilan_gt_medyan():
    # İlan fiyatı > Medyan
    detail = ListingDetail(
        ilan_no="1", url="", baslik="", marka="", model="",
        fiyat=1100000, yil=2020, km=50000, il="", ilan_tarihi=date.today(),
        parts={}, aciklama="", fetched_at=datetime.now(timezone.utc)
    )
    findings = get_base_findings()
    market = MarketStats(n=10, medyan=1000000, p25=950000, p75=1050000, guven="yuksek")
    verdict = Verdict(ilan_no="1", etiket="ALINIR", guven_skoru=8.0, veri_tamlik=1.0, piyasa=market)
    
    offer = calculate_offer(detail, findings, verdict)
    assert offer is not None
    # Baz fiyat 1.000.000 olacak (min). İndirim yok (0). Hedef: 1.000.000.
    # Güven 8.0 -> pazarlık %2 -> Açılış: 980.000.
    assert offer[0] == 980000
    assert offer[1] == 1000000

def test_offer_ilan_lt_medyan():
    # İlan fiyatı < Medyan, indirimler var
    detail = ListingDetail(
        ilan_no="1", url="", baslik="", marka="", model="",
        fiyat=950000, yil=2020, km=100000, il="", ilan_tarihi=date.today(),
        parts={"sag_kapi": "boyali", "kaput": "degisen"}, # boya %2 + degisen %4 = %6
        aciklama="", fetched_at=datetime.now(timezone.utc)
    )
    findings = get_base_findings()
    # Yıllık km (4 yaşında 100k) = 25000
    market = MarketStats(n=10, medyan=1000000, p25=950000, p75=1050000, guven="yuksek")
    verdict = Verdict(ilan_no="1", etiket="ALINIR", guven_skoru=6.0, veri_tamlik=1.0, piyasa=market)
    
    offer = calculate_offer(detail, findings, verdict)
    assert offer is not None
    # Baz: 950.000
    # İndirim: %6 (parça)
    # Hedef: 950.000 * 0.94 = 893.000
    # Pazarlık: %4 (güven 6.0) -> 893.000 * 0.96 = 857.280
    # Yuvarlama: 855.000
    assert offer[0] == 855000
    
def test_offer_taban_fiyat():
    # Çok fazla indirim var, taban fiyata çarpmalı
    detail = ListingDetail(
        ilan_no="1", url="", baslik="", marka="", model="",
        fiyat=1000000, yil=2020, km=200000, il="", ilan_tarihi=date.today(),
        parts={"kaput": "degisen", "tavan": "degisen", "kapi": "degisen", "camurluk": "degisen"}, # >%15
        aciklama="", fetched_at=datetime.now(timezone.utc)
    )
    findings = get_base_findings()
    market = MarketStats(n=10, medyan=1000000, p25=950000, p75=1050000, guven="yuksek")
    verdict = Verdict(ilan_no="1", etiket="ALINIR", guven_skoru=5.0, veri_tamlik=1.0, piyasa=market)
    
    offer = calculate_offer(detail, findings, verdict)
    assert offer is not None
    # İndirim max %15'e takılır. Hedef: 850.000. 
    # Pazarlıkla 850 * 0.96 = 816.000. Ama taban fiyat 1000000 * 0.85 = 850.000. 
    # Sonuç 850.000 olmalı.
    assert offer[0] == 850000
    
def test_offer_alinmaz():
    verdict = Verdict(ilan_no="1", etiket="ALINMAZ", guven_skoru=2.0, veri_tamlik=1.0)
    assert calculate_offer(None, None, verdict) is None
