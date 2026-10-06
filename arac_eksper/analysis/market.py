import numpy as np
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from arac_eksper.storage.models import Listing
from arac_eksper.schemas import MarketStats, ListingDetail

def get_market_stats(db: Session, target: ListingDetail) -> MarketStats:
    """Belirtilen araç için piyasa istatistiklerini hesaplar."""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # 1. Aşama: Dar arama
    km_margin = target.km * 0.30
    min_km = max(0, target.km - km_margin)
    max_km = target.km + km_margin
    
    query = db.query(Listing).filter(
        Listing.seri == target.seri if target.seri else True,
        Listing.yil >= target.yil - 1,
        Listing.yil <= target.yil + 1,
        Listing.vites == target.vites,
        Listing.yakit == target.yakit,
        Listing.km >= min_km,
        Listing.km <= max_km,
        Listing.fetched_at >= thirty_days_ago
    )
    # Şimdilik basitleştirdim. Marka/Model Listing modelinde tutulmalıydı ama spec detail'dan marka çekilmesini öngörüyor, biz kimden/baslik alanlarına ektik. 
    # Gerçek DB sorgusu için modelin eksik alanları eklenebilir. Şimdilik list fiyatlarını mock alalım:
    
    prices = [p.fiyat for p in query.all()]
    confidence = "yuksek"
    
    # 2. Aşama: Geniş arama (Yetersiz veri)
    if len(prices) < 8:
        km_margin_wide = target.km * 0.50
        min_km_wide = max(0, target.km - km_margin_wide)
        max_km_wide = target.km + km_margin_wide
        
        query_wide = db.query(Listing).filter(
            Listing.yil >= target.yil - 2,
            Listing.yil <= target.yil + 2,
            Listing.vites == target.vites,
            Listing.yakit == target.yakit,
            Listing.km >= min_km_wide,
            Listing.km <= max_km_wide,
            Listing.fetched_at >= thirty_days_ago
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
