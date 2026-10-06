import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from arac_eksper.parser.damage_parser import parse as parse_damage
from arac_eksper.parser.list_parser import parse_date, parse_price
from arac_eksper.parser.selectors import Selectors
from arac_eksper.privacy import mask_phones
from arac_eksper.schemas import ListingDetail


def _req(soup, sel: str, ad: str) -> str:
    el = soup.select_one(sel)
    if not el:
        raise ValueError(f"{ad} okunamadı")
    return el.get_text(" ", strip=True)


def parse(html: str, url: str = "", il: str = "Bilinmiyor", ilce: str | None = None) -> ListingDetail:
    """Gerçek ilan sayfası (R0.4). Konum detay sayfasından okunmaz; arama satırından gelir (il/ilce parametresi)."""
    soup = BeautifulSoup(html, "lxml")
    info = {}
    for item in soup.select(Selectors.DETAIL_INFO_LIST):
        label, value = item.select_one(Selectors.DETAIL_INFO_LABEL), item.select_one(Selectors.DETAIL_INFO_VALUE)
        if label and value:
            info[label.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    ilan_no = info.get("İlan No", "")
    if not re.fullmatch(r"\d{1,12}", ilan_no):
        raise ValueError("ilan no okunamadı")
    yil_str = info.get("Yıl", "")
    if not yil_str.isdigit():
        raise ValueError("yıl okunamadı")   # 0'a düşmesin: yıl=0 araç yaşını ve piyasa kümesini bozar
    km_str = info.get("KM", "").replace(".", "")
    if not km_str.isdigit():
        raise ValueError("km okunamadı")    # km=0 "neredeyse sıfır araç" gibi görünürdü
    hasar_raw = info.get("Ağır Hasar Kayıtlı")
    hasar = None if hasar_raw is None else hasar_raw.strip().lower() == "evet"   # alan yoksa bilinmiyor, "hayır" değil
    aciklama = soup.select_one(Selectors.DETAIL_ACIKLAMA)
    return ListingDetail(
        ilan_no=ilan_no, url=url, baslik=_req(soup, Selectors.DETAIL_BASLIK, "başlık"),
        fiyat=parse_price(_req(soup, Selectors.DETAIL_FIYAT, "fiyat")), yil=int(yil_str), km=int(km_str),
        il=il, ilce=ilce, ilan_tarihi=parse_date(info.get("İlan Tarihi", "")),
        marka=info.get("Marka", ""), model=info.get("Seri", ""),  # site: Marka > Seri (=model adı) > Model (=paket)
        seri=info.get("Seri"), paket=info.get("Model"), vites=info.get("Vites"), yakit=info.get("Yakıt / Motor Tipi"),
        kasa_tipi=info.get("Kasa Tipi"), motor_hacmi=info.get("Motor Hacmi"), renk=info.get("Renk"),
        kimden=info.get("Kimden"), agir_hasar_kayitli=hasar, parts=parse_damage(html),
        aciklama=mask_phones(aciklama.get_text("\n", strip=True) if aciklama else ""),
        fetched_at=datetime.now(timezone.utc))
