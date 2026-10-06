"""Tarayıcıdan 'Farklı kaydet' ile alınan ilan sayfasını test fixture'ı yapmadan önce kişisel veriden arındırır.

Otomatik: script/iframe/gizli form alanı/yorum silinir; metin ve öznitelikte telefon, e-posta, plaka maskelenir;
tel:/mailto: bağlantıları düşer. Satıcı ADI biçimden tanınamaz: kullanıcı/satıcı/iletişim gibi görünen bloklar
raporlanır, kullanıcı bunları --remove CSS seçicisiyle siler. Rapor metin İÇERİĞİ basmaz (yalnız etiket/sınıf/uzunluk).
"""
import re

from bs4 import BeautifulSoup, Comment

from arac_eksper.privacy import mask_phones

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Türk plakası: il kodu 01-81, 1-3 harf, 2-4 rakam ("34 ABC 123", "16AB1234"); "/" sonrası değil (lastik 205/55 R16)
_PLATE = re.compile(r"(?<![\w./])(0[1-9]|[1-7]\d|8[01])\s?[A-PR-VYZ]{1,3}\s?\d{2,4}(?!\w|\.\w)")
_DROP_TAGS = ("script", "noscript", "iframe", "object", "embed", "template")
# Harita/konum öznitelikleri (satıcının konumu olabilir): değeriyle birlikte silinir
_GEO_ATTR = re.compile(r"(^|[-_])(lat|lon|lng|latitude|longitude|coords?|geo)($|[-_])", re.I)
_SUSPECT = re.compile(r"user|seller|owner|member|profile|username|store|magaza|iletisim|contact|phone|telefon|"
                      r"avatar|login|account|hesap", re.I)


def _mask(text: str, counts: dict) -> str:
    for key, fn in (("telefon", mask_phones),
                    ("eposta", lambda t: _EMAIL.sub("[eposta]", t)),
                    ("plaka", lambda t: _PLATE.sub("[plaka]", t))):
        new = fn(text)
        if new != text:
            counts[key] += 1
            text = new
    return text


def sanitize(html: str, remove: list[str] | None = None) -> tuple[str, dict]:
    soup = BeautifulSoup(html, "lxml")
    rep = {"silinen_etiket": 0, "silinen_secici": {}, "maskelenen": {"telefon": 0, "eposta": 0, "plaka": 0},
           "supheli_bloklar": []}

    for el in soup.find_all(_DROP_TAGS):
        el.decompose()
        rep["silinen_etiket"] += 1
    for el in soup.select('input[type="hidden"], meta[name*="csrf" i], meta[name*="token" i]'):
        el.decompose()
        rep["silinen_etiket"] += 1
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for sel in remove or []:
        found = soup.select(sel)
        rep["silinen_secici"][sel] = len(found)
        for el in found:
            el.decompose()

    for s in soup.find_all(string=True):
        new = _mask(str(s), rep["maskelenen"])
        if new != s:
            s.replace_with(new)
    for el in soup.find_all(True):
        for attr, val in list(el.attrs.items()):
            if _GEO_ATTR.search(attr):
                del el.attrs[attr]
                rep["silinen_konum"] = rep.get("silinen_konum", 0) + 1
                continue
            if attr == "href" and isinstance(val, str) and val.lower().startswith(("tel:", "mailto:")):
                del el.attrs[attr]
                continue
            if attr == "value" and el.name in ("input", "textarea"):
                del el.attrs[attr]          # form değerleri (arama kutusu, oturum alanları) fixture'a girmez
                continue
            if isinstance(val, str):
                el.attrs[attr] = _mask(val, rep["maskelenen"])

    seen = set()
    for el in soup.find_all(True):
        ident = " ".join([el.get("id") or ""] + list(el.get("class") or []))
        if ident.strip() and _SUSPECT.search(ident) and el.get_text(strip=True):
            parent_flagged = any(p in seen for p in el.parents)
            seen.add(el)
            if not parent_flagged:
                css = el.name + (f"#{el['id']}" if el.get("id") else "") + "".join(f".{c}" for c in el.get("class") or [])
                rep["supheli_bloklar"].append({"secici": css, "metin_uzunlugu": len(el.get_text(strip=True))})
    return str(soup), rep
