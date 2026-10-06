from bs4 import BeautifulSoup
from typing import Dict
from arac_eksper.schemas import PartState
from arac_eksper.parser.selectors import Selectors

def parse(html: str) -> Dict[str, PartState]:
    soup = BeautifulSoup(html, "lxml")
    parts = {}
    
    part_els = soup.select(Selectors.DAMAGE_PART)
    for el in part_els:
        name = el.get("data-name")
        state_str = el.get("data-state")
        if name and state_str:
            try:
                parts[name] = PartState(state_str)
            except ValueError:
                parts[name] = PartState.UNKNOWN
                
    return parts
