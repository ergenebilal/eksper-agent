import numpy as np
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from arac_eksper.storage.models import Listing
from arac_eksper.schemas import MarketStats, ListingDetail

def _tolerant_eq(column, value):
    """Değer biliniyorsa eşleşme ya da bilinmeyen (NULL) kayıt kabul edilir.
    Liste sayfasından gelen emsallerde vites/yakıt/seri çoğu zaman yoktur."""
    if value is None or value == "":
        return None
    return or_(column.is_(None), func.lower(column) == str(value).lower())


def _base_filters(target: ListingDetail, thirty_days_ago):
    filters = [
        func.lower(Listing.marka) == (target.marka or "").lower(),
        func.lower(Listing.model) == (target.model or "").lower(),
        Listing.ilan_no != target.ilan_no,
        Listing.fetched_at >= thirty_days_ago,
    ]
    for col, val in ((Listing.seri, target.seri), (Listing.vites, target.vites), (Listing.yakit, target.yakit)):
        cond = _tolerant_eq(col, val)
        if cond is not None:
            filters.append(cond)
    return filters


def get_market_stats(db: Session, target: ListingDetail) -> MarketStats:
    """Belirtilen araç için piyasa istatistiklerini hesaplar."""
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    if not (target.marka and target.model):
        # Marka/model bilinmiyorsa emsal aranamaz; yanlış kümeyle kıyaslamaktansa "yok" dön.
        return MarketStats(n=0, medyan=0, p25=0, p75=0, guven="yok")

    # 1. Aşama: Dar arama
    km_margin = target.km * 0.30
    base = _base_filters(target, thirty_days_ago)

    query = db.query(Listing).filter(
        *base,
        Listing.yil >= target.yil - 1,
        Listing.yil <= target.yil + 1,
        Listing.km >= max(0, target.km - km_margin),
        Listing.km <= target.km + km_margin,
    )

    prices = [p.fiyat for p in query.all()]
    confidence = "yuksek"
    
    # 2. Aşama: Geniş arama (Yetersiz veri)
    if len(prices) < 8:
        km_margin_wide = target.km * 0.50
        min_km_wide = max(0, target.km - km_margin_wide)
        max_km_wide = target.km + km_margin_wide
        
        query_wide = db.query(Listing).filter(
            *base,
            Listing.yil >= target.yil - 2,
            Listing.yil <= target.yil + 2,
            Listing.km >= min_km_wide,
            Listing.km <= max_km_wide
        )
        prices = [p.fiyat for p in query_wide.all()]
        confidence = "dusuk"
        
    if not prices:
        return MarketStats(n=0, medyan=0, p25=0, p75=0, guven="yok")
        
    # Aykırı değerleri temizle (IQR)
    q1 = np.percentile(prices, 25)
    q3 = np.percentile(prices, 75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    
    valid_prices = [p for p in prices if lower_bound <= p <= upper_bound]
    if not valid_prices:
        valid_prices = prices # eğer hepsi atıldıysa geri al
        
    n = len(valid_prices)
    medyan = int(np.median(valid_prices))
    p25 = int(np.percentile(valid_prices, 25))
    p75 = int(np.percentile(valid_prices, 75))
    
    return MarketStats(n=n, medyan=medyan, p25=p25, p75=p75, guven=confidence)
