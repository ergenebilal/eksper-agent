import yaml
from pathlib import Path
from arac_eksper.schemas import ListingDetail


def load_kb() -> list[dict]:
    path = Path(__file__).parent.parent / "config" / "models_kb.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("models", []) or []


def kronik_arizalar(detail: ListingDetail, kb: list[dict] | None = None) -> list[dict]:
    """Aracın marka/model/yılına uyan kronik arıza kayıtları: [{etiket, kontrol}]."""
    kb = load_kb() if kb is None else kb
    out = []
    for entry in kb:
        if (entry.get("marka", "").lower() != (detail.marka or "").lower()
                or entry.get("model", "").lower() != (detail.model or "").lower()):
            continue
        if entry.get("yil_min") and detail.yil < entry["yil_min"]:
            continue
        if entry.get("yil_max") and detail.yil > entry["yil_max"]:
            continue
        out.extend(entry.get("kronik", []))
    return out
