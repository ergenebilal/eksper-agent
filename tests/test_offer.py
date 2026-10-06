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



def _detail(**kw):
    base = dict(ilan_no="1", url="", baslik="", marka="", model="", fiyat=1_000_000, yil=2022, km=40000, il="",
                ilan_tarihi=date.today(), parts={}, aciklama="", fetched_at=datetime(2026, 10, 6, tzinfo=timezone.utc))
    base.update(kw)
    return ListingDetail(**base)


MKT = MarketStats(n=10, medyan=1_000_000, p25=950000, p75=1050000, guven="yuksek")


def test_breakdown_gives_same_numbers_as_calculate_offer_and_explains_every_item():
    from arac_eksper.analysis.offer import breakdown
    from arac_eksper.schemas import PartState
    d = _detail(parts={"tavan": PartState.ORIGINAL, "sag_arka_camurluk": PartState.REPLACED, "kaput": PartState.PAINTED,
                       "on_tampon": PartState.PAINTED}, km=150000)
    f = get_base_findings()
    f.tramer_tutari = 30000
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=6.5, veri_tamlik=1.0, piyasa=MKT)
    b = breakdown(d, f, v)
    assert (b["acilis"], b["ust_sinir"]) == calculate_offer(d, f, v) and b["kaynak"] == "piyasa"
    text = " | ".join(b["dayanak"])
    for needle in ("Piyasa ortalaması", "1 değişen parça", "1 boyalı parça", "Tramer 30.000 TL", "Yıllık km", "Pazarlık payı"):
        assert needle in text, needle
    assert "tampon" not in text.lower()                          # tampon kozmetik: indirim yok
    assert b["acilis"] <= b["hedef"] <= b["ust_sinir"] <= d.fiyat


def test_no_market_gives_a_labelled_offer_from_listing_price_only():
    from arac_eksper.analysis.offer import breakdown
    from arac_eksper.schemas import PartState
    d = _detail(parts={"sol_kapi": PartState.REPLACED})
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=8.0, veri_tamlik=0.3)
    assert calculate_offer(d, get_base_findings(), v) is None                   # eski davranış korunur
    b = breakdown(d, get_base_findings(), v, allow_no_market=True)
    assert b["kaynak"] == "ilan" and "Piyasa verisi yok" in b["dayanak"][0]
    assert b["baz"] == 1_000_000 and b["acilis"] < b["hedef"] <= b["ust_sinir"] <= 1_000_000
    assert not any("Taban" in x for x in b["dayanak"])                          # piyasa yokken taban uygulanmaz


def test_no_offer_for_red_or_pending_even_without_market():
    from arac_eksper.analysis.offer import breakdown
    d = _detail()
    assert breakdown(d, get_base_findings(), Verdict(ilan_no="1", etiket="ALINMAZ", guven_skoru=2, veri_tamlik=1), True) is None
    assert breakdown(d, get_base_findings(), Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=0, veri_tamlik=0,
                                                     beklemede=True), True) is None


def test_no_offer_figure_ever_exceeds_the_asking_price_even_after_rounding():
    """Gerçek hata: ilan 1.499.000 TL iken yuvarlama 1.500.000 TL'ye çıkarıyordu."""
    from arac_eksper.analysis.offer import breakdown
    for fiyat in (1_499_000, 1_499_999, 1_003_000, 987_654, 2_999_000):
        d = _detail(fiyat=fiyat)
        v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=8.0, veri_tamlik=1.0)
        b = breakdown(d, get_base_findings(), v, allow_no_market=True)
        assert b["acilis"] <= b["anlasma"] <= b["ust_sinir"] <= fiyat, (fiyat, b)
        assert b["hedef"] <= b["ust_sinir"] and b["baz"] <= fiyat


def test_settlement_point_is_between_opening_and_upper_limit_not_the_asking_price():
    from arac_eksper.analysis.offer import breakdown
    d = _detail(fiyat=1_499_000)
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=8.0, veri_tamlik=1.0)
    b = breakdown(d, get_base_findings(), v, allow_no_market=True)
    assert b["acilis"] < b["anlasma"] < b["ust_sinir"] or (b["acilis"] < b["anlasma"] <= b["ust_sinir"])
    assert b["anlasma"] < 1_499_000                       # ilan fiyatının kendisi "makul anlaşma" değildir


def test_few_comparables_do_not_become_the_market_for_the_offer():
    from arac_eksper.analysis.offer import breakdown
    d = _detail(fiyat=1_499_000)
    few = MarketStats(n=2, medyan=1_200_000, p25=1_190_000, p75=1_210_000, guven="dusuk")
    v = Verdict(ilan_no="1", etiket="DUSUNULEBILIR", guven_skoru=8.0, veri_tamlik=1.0, piyasa=few)
    assert calculate_offer(d, get_base_findings(), v) is None
    b = breakdown(d, get_base_findings(), v, allow_no_market=True)
    assert b["kaynak"] == "ilan" and "Emsal az (n=2" in b["dayanak"][0]
    assert b["baz"] <= 1_499_000                          # 2 ilanın medyanı (1.2M) baz alınmadı
