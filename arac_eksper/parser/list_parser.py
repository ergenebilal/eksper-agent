from bs4 import BeautifulSoup
from typing import List, Tuple, Optional
from datetime import datetime
from arac_eksper.schemas import ListingSummary
from arac_eksper.parser.selectors import Selectors

def parse_price(price_str: str) -> int:
    return int(''.join(filter(str.isdigit, price_str)))

def parse_date(date_str: str) -> datetime.date:
    # Basit mock tarih çevirici, gerçekte "15 Mayıs 2024" formatını vs parse etmeli
    months = {"Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6, "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12}
    parts = date_str.split()
    if len(parts) == 3:
        day, month_str, year = parts
        month = months.get(month_str, 1)
        return datetime(int(year), month, int(day)).date()
    return datetime.today().date()

def parse(html: str) -> Tuple[List[ListingSummary], Optional[str]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []
    
    items = soup.select(Selectors.LIST_ITEM)
    for item in items:
        link_el = item.select_one(Selectors.LIST_ILAN_LINK)
        if not link_el: continue
        
        ilan_no = item.select_one(Selectors.LIST_ILAN_NO).text.strip()
        baslik = item.select_one(Selectors.LIST_BASLIK).text.strip()
        fiyat_str = item.select_one(Selectors.LIST_FIYAT).text.strip()
        fiyat = parse_price(fiyat_str)
        yil = int(item.select_one(Selectors.LIST_YIL).text.strip())
        km = int(item.select_one(Selectors.LIST_KM).text.strip().replace('.', ''))
        il = item.select_one(Selectors.LIST_IL).text.strip()
        
        ilce_el = item.select_one(Selectors.LIST_ILCE)
        ilce = ilce_el.text.strip() if ilce_el else None
        
        tarih_str = item.select_one(Selectors.LIST_TARIH).text.strip()
        ilan_tarihi = parse_date(tarih_str)
        
        listings.append(ListingSummary(
            ilan_no=ilan_no,
            url=link_el["href"],
            baslik=baslik,
            fiyat=fiyat,
            yil=yil,
            km=km,
            il=il,
            ilce=ilce,
            ilan_tarihi=ilan_tarihi
        ))
        
    next_page_el = soup.select_one(Selectors.LIST_NEXT_PAGE)
    next_page_url = next_page_el["href"] if next_page_el else None
    
    return listings, next_page_url
