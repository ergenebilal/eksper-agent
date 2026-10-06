"""Marka/model çıkarımı. Sahibinden liste satırlarında marka/model ayrı alan olarak gelmeyebilir; kullanıcının
`category_map.yaml` kayıtları (arac map add) ve DB'de görülen marka/modeller bilinen küme sayılır.
Tahmin yok: eşleşme yoksa (None, None) döner ve ilan piyasa kümesine girmez ("bilinmeyen iyi sayılmaz")."""
import re
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from arac_eksper.collector import url_builder
from arac_eksper.storage.models import Listing


def _fold(s: str) -> str:
    s = (s or "").replace("İ", "i").replace("I", "ı").lower()
    return s.translate(str.maketrans("çşğöüı", "csgoui"))


def _tokens(s: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9.]+", _fold(s))) + " "


def known_models(db: Session | None) -> set[tuple[str, str]]:
    out = set()
    for marka, models in (url_builder.load_category_map() or {}).items():
        for model in (models or {}):
            out.add((marka, model))
    if db is not None:
        out |= {(m, md) for m, md in db.query(Listing.marka, Listing.model).distinct().all() if m and md}
    return out


def from_path(path: str | None) -> tuple[str | None, str | None]:
    """Arama sayfasının ilk yol parçası kategori haritasındaki bir slug ise marka/model kesindir."""
    if not path:
        return None, None
    seg = urlsplit(path).path.strip("/").split("/")[0].lower()
    if not seg:
        return None, None
    for marka, models in (url_builder.load_category_map() or {}).items():
        for model, val in (models or {}).items():
            slugs = [val] if isinstance(val, str) else list((val or {}).values())
            if any(str(s).lower() == seg for s in slugs):
                return marka, model
    return None, None


def from_title(baslik: str | None, db: Session | None = None) -> tuple[str | None, str | None]:
    """Başlıkta hem marka hem model sözcükleri geçen EN UZUN bilinen eşleşme."""
    if not baslik:
        return None, None
    text, best = _tokens(baslik), None
    for marka, model in known_models(db):
        if _tokens(marka) in text and _tokens(model) in text:
            if best is None or len(model) > len(best[1]):
                best = (marka, model)
    return best if best else (None, None)


def resolve(marka: str | None, model: str | None, baslik: str | None, page_path: str | None,
            db: Session | None = None) -> tuple[str | None, str | None]:
    """Öncelik: açık alan > sayfa adresi (kategori haritası) > başlık."""
    if marka and model:
        return marka, model
    for fn in (lambda: from_path(page_path), lambda: from_title(baslik, db)):
        m, md = fn()
        if m and md:
            return m, md
    return None, None
