from typing import Dict

from bs4 import BeautifulSoup

from arac_eksper.parser.selectors import PART_CLASS, STATE_CLASS, Selectors
from arac_eksper.schemas import PartState


def parse(html: str) -> Dict[str, PartState]:
    """Hasar şeması: `.car-parts > div` → 1. sınıf parça, 2. sınıf durum. Tanınmayan durum eklenmez (bilinmiyor).
    Doldurulmamış şema 'orijinal' görünür; bunu ayırt etmek analysis/diagram_check.py'nin işidir."""
    soup = BeautifulSoup(html, "lxml")
    parts: Dict[str, PartState] = {}
    for el in soup.select(Selectors.DAMAGE_PART):
        cls = el.get("class") or []
        name = next((PART_CLASS[c] for c in cls if c in PART_CLASS), None)
        state = next((STATE_CLASS[c] for c in cls if c in STATE_CLASS), None)
        if name and state:
            parts[name] = PartState(state)
    return parts
