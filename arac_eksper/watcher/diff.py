"""Liste sayfasından gelen ilanlarda değişiklik tespiti: yeni ilan, fiyat düşüşü, yeniden yayın.
ÖNEMLİ: summary'ler DB'ye yazılmadan ÖNCE çağrılmalı (yazınca eski fiyat kaybolur)."""
import re
from dataclasses import dataclass, field
from typing import List, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session
from arac_eksper.storage.models import Listing
from arac_eksper.schemas import ListingSummary
from arac_eksper.config.rules_loader import load_rules



@dataclass
class ChangeSet:
    new: List[ListingSummary] = field(default_factory=list)
    price_drops: List[Tuple[ListingSummary, int, int]] = field(default_factory=list)   # (özet, eski, yeni)
    republished: List[Tuple[ListingSummary, str]] = field(default_factory=list)        # (özet, eski ilan_no)


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def detect_changes(db: Session, summaries: List[ListingSummary], marka: str = "", model: str = "") -> ChangeSet:
    cs = ChangeSet()
    drop = load_rules()["radar"]["fiyat_dusus_orani"]
    for s in summaries:
        row = db.query(Listing).filter(Listing.ilan_no == s.ilan_no).first()
        if row is None:
            old = (db.query(Listing)
                   .filter(Listing.ilan_no != s.ilan_no, Listing.km == s.km, Listing.yil == s.yil,
                           func.lower(Listing.marka) == marka.lower(), func.lower(Listing.model) == model.lower())
                   .all())
            twin = next((o for o in old if _norm_title(o.baslik) == _norm_title(s.baslik)), None)
            if twin:
                cs.republished.append((s, twin.ilan_no))   # aynı araç, yeni ilan no
            else:
                cs.new.append(s)
        elif s.fiyat < row.fiyat and (row.fiyat - s.fiyat) / row.fiyat >= drop:
            cs.price_drops.append((s, row.fiyat, s.fiyat))
    return cs
