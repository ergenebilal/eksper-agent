import datetime as dt
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from arac_eksper.parser.selectors import Selectors
from arac_eksper.schemas import ListingSummary

AYLAR = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
         "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}


def parse_price(price_str: str) -> int:
    return int("".join(filter(str.isdigit, price_str)))


def parse_date(date_str: str) -> dt.date:
    """'04 Ekim 2026' (satır sonu da olabilir) → date. Okunamazsa ValueError: bugünün tarihi UYDURULMAZ."""
    p = date_str.split()
    if len(p) == 3 and p[0].isdigit() and p[2].isdigit():
        ay = AYLAR.get(p[1].replace("I", "ı").replace("İ", "i").lower())
        if ay:
            return dt.date(int(p[2]), ay, int(p[0]))
    raise ValueError(f"tarih okunamadı: {date_str!r}")


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def parse(html: str) -> Tuple[List[ListingSummary], Optional[str]]:
    soup = BeautifulSoup(html, "lxml")
    headers = [_text(td) for td in soup.select(Selectors.LIST_HEADER_CELLS)]
    tag_cols = [h for h in headers if h in ("Marka", "Seri", "Model")]
    attr_cols = [h for h in headers if h in ("Yıl", "KM")]
    listings = []
    for row in soup.select(Selectors.LIST_ITEM):
        link = row.select_one(Selectors.LIST_ILAN_LINK)
        no = row.get(Selectors.LIST_ILAN_NO_ATTR)
        if not link or not no:
            continue
        tags = dict(zip(tag_cols, [_text(td) for td in row.select(Selectors.LIST_TAG)]))
        attrs = dict(zip(attr_cols, [_text(td) for td in row.select(Selectors.LIST_ATTR)]))
        konum = row.select_one(Selectors.LIST_KONUM)
        il_ilce = [s.strip() for s in konum.get_text("\n").split("\n") if s.strip()] if konum else []
        try:
            listings.append(ListingSummary(
                ilan_no=no, url=link["href"], baslik=_text(row.select_one(Selectors.LIST_BASLIK)),
                marka=tags.get("Marka", ""), model=tags.get("Seri", ""),
                fiyat=parse_price(_text(row.select_one(Selectors.LIST_FIYAT))),
                yil=int(attrs["Yıl"]), km=parse_price(attrs["KM"]),
                il=il_ilce[0] if il_ilce else "Bilinmiyor", ilce=il_ilce[1] if len(il_ilce) > 1 else None,
                ilan_tarihi=parse_date(_text(row.select_one(Selectors.LIST_TARIH)))))
        except (KeyError, ValueError):
            continue                                   # okunamayan satır "iyi" sayılmaz: atlanır
    nxt = None
    pages = soup.select_one(Selectors.LIST_PAGES)
    cur = pages.select_one(Selectors.LIST_CURRENT_PAGE) if pages else None
    if cur and _text(cur).isdigit():
        a = pages.find("a", title=str(int(_text(cur)) + 1))
        nxt = a["href"] if a else None
    return listings, nxt
