from typing import List, Tuple
from sqlalchemy.orm import Session
from arac_eksper.storage.models import Listing
from arac_eksper.schemas import ListingSummary

def find_new_and_dropped_listings(db: Session, summaries: List[ListingSummary]) -> Tuple[List[ListingSummary], List[Tuple[ListingSummary, int, int]]]:
    """
    Yeni ilanları ve fiyatı düşenleri tespit eder.
    Returns:
        new_listings: Daha önce veritabanında olmayan ilanlar.
        price_drops: (Summary, Eski_Fiyat, Yeni_Fiyat) formatında fiyatı düşen ilanlar.
    """
    new_listings = []
    price_drops = []
    
    for summary in summaries:
        db_listing = db.query(Listing).filter(Listing.ilan_no == summary.ilan_no).first()
        
        if not db_listing:
            # Belki ilan no değişip aynı araç tekrar koyulmuştur? (yeniden yayın)
            # Basit kontrol: km ve yıl aynı, başlık benzerse
            # Şimdilik bunu basit tutuyoruz, sadece ilan no'ya bakıyoruz
            new_listings.append(summary)
        else:
            if summary.fiyat < db_listing.fiyat:
                # Fiyat düşüşü %3'ten büyük mü?
                if (db_listing.fiyat - summary.fiyat) / db_listing.fiyat >= 0.03:
                    price_drops.append((summary, db_listing.fiyat, summary.fiyat))
                    
    return new_listings, price_drops
