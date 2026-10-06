from bs4 import BeautifulSoup
from datetime import datetime, timezone
from arac_eksper.schemas import ListingDetail, PartState
from arac_eksper.parser.selectors import Selectors
from arac_eksper.parser.list_parser import parse_price, parse_date
from arac_eksper.parser.damage_parser import parse as parse_damage

def parse(html: str, url: str = "") -> ListingDetail:
    soup = BeautifulSoup(html, "lxml")
    
    ilan_no = soup.select_one(Selectors.DETAIL_ILAN_NO).text.strip()
    baslik = soup.select_one(Selectors.DETAIL_BASLIK).text.strip()
    fiyat = parse_price(soup.select_one(Selectors.DETAIL_FIYAT).text.strip())
    aciklama = soup.select_one(Selectors.DETAIL_ACIKLAMA).text.strip()
    
    info_items = soup.select(Selectors.DETAIL_INFO_LIST)
    info_dict = {}
    for item in info_items:
        label = item.select_one(Selectors.DETAIL_INFO_LABEL).text.strip()
        value = item.select_one(Selectors.DETAIL_INFO_VALUE).text.strip()
        info_dict[label] = value
        
    il_ilce = info_dict.get("İl / İlçe", " / ").split(" / ")
    il = il_ilce[0].strip() if len(il_ilce) > 0 else "Bilinmiyor"
    ilce = il_ilce[1].strip() if len(il_ilce) > 1 else None
    
    tarih_str = info_dict.get("İlan Tarihi", "")
    ilan_tarihi = parse_date(tarih_str)
    
    yil_str = info_dict.get("Yıl", "0")
    yil = int(yil_str) if yil_str.isdigit() else 0
    
    km_str = info_dict.get("Kilometre", "0").replace(".", "")
    km = int(km_str) if km_str.isdigit() else 0
    
    hasar = info_dict.get("Ağır Hasar Kayıtlı", "Hayır").lower() == "evet"
    
    parts = parse_damage(html)
    
    return ListingDetail(
        ilan_no=ilan_no,
        url=url,
        baslik=baslik,
        fiyat=fiyat,
        yil=yil,
        km=km,
        il=il,
        ilce=ilce,
        ilan_tarihi=ilan_tarihi,
        marka=info_dict.get("Marka", ""),
        model=info_dict.get("Seri", ""),  # sahibinden: Marka > Seri (=model adı) > Model (=paket)
        seri=info_dict.get("Seri"),
        paket=info_dict.get("Model"),
        vites=info_dict.get("Vites"),
        yakit=info_dict.get("Yakıt Tipi"),
        kasa_tipi=info_dict.get("Kasa Tipi"),
        motor_hacmi=info_dict.get("Motor Hacmi"),
        renk=info_dict.get("Renk"),
        kimden=info_dict.get("Kimden"),
        agir_hasar_kayitli=hasar,
        parts=parts,
        aciklama=aciklama,
        fetched_at=datetime.now(timezone.utc)
    )
