import numpy as np
from sqlalchemy import and_, or_, func
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


def _strict_eq(column, value):
    """Bilinen değerle tam eşleşme; NULL (liste kaydı, vites/yakıt bilinmiyor) EŞLEŞMEZ."""
    if value is None or value == "":
        return None
    return func.lower(column) == str(value).lower()


def _base_filters(target: ListingDetail, thirty_days_ago, strict: bool = False):
    eq = _strict_eq if strict else _tolerant_eq
    filters = [
        func.lower(Listing.marka) == (target.marka or "").lower(),
        func.lower(Listing.model) == (target.model or "").lower(),
        Listing.ilan_no != target.ilan_no,
        Listing.fetched_at >= thirty_days_ago,
        # Aynı aracın yeniden yayını (farklı ilan no, aynı başlık+yıl+km) kendi emsali olamaz
        ~and_(Listing.km == target.km, Listing.yil == target.yil,
              func.lower(Listing.baslik) == (target.baslik or "").lower()),
    ]
    for col, val in ((Listing.seri, target.seri), (Listing.vites, target.vites), (Listing.yakit, target.yakit)):
        cond = eq(col, val)
        if cond is not None:
            filters.append(cond)
    return filters


def get_market_stats(db: Session, target: ListingDetail) -> MarketStats:
    """Belirtilen araç için piyasa istatistiklerini hesaplar."""
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    if not (target.marka and target.model):
        # Marka/model bilinmiyorsa emsal aranamaz; yanlış kümeyle kıyaslamaktansa "yok" dön.
        return MarketStats(n=0, medyan=0, p25=0, p75=0, guven="yok")

    km_margin = target.km * 0.30

    def narrow(strict: bool):
        return [p.fiyat for p in db.query(Listing).filter(
            *_base_filters(target, thirty_days_ago, strict=strict),
            Listing.yil >= target.yil - 1, Listing.yil <= target.yil + 1,
            Listing.km >= max(0, target.km - km_margin), Listing.km <= target.km + km_margin).all()]

    # 1. Aşama: dar arama, vites/yakıt/seri BİLİNEN kayıtlarla (liste kayıtlarındaki NULL'lar karışmasın)
    prices = narrow(strict=True)
    confidence = "yuksek"

    # 2. Aşama: bilinmeyen (NULL) vites/yakıt/seri kabul edilir → güven düşer
    if len(prices) < 8:
        prices = narrow(strict=False)
        confidence = "dusuk"

    # 3. Aşama: geniş arama (yıl ±2, km ±%50)
    if len(prices) < 8:
        km_margin_wide = target.km * 0.50
        prices = [p.fiyat for p in db.query(Listing).filter(
            *_base_filters(target, thirty_days_ago),
            Listing.yil >= target.yil - 2, Listing.yil <= target.yil + 2,
            Listing.km >= max(0, target.km - km_margin_wide), Listing.km <= target.km + km_margin_wide).all()]
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
