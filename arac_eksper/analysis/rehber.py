"""Statik rehber içerikleri (config/alim_gunu.yaml): alım günü / noter kontrol listesi (OtoXray_Arge.md R1.3).
Kural 10: yalnız `onayli: true` ise sunulur."""
from pathlib import Path

import yaml

ALIM_GUNU_PATH = Path(__file__).parent.parent / "config" / "alim_gunu.yaml"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_alim_gunu(include_unapproved: bool = False, path: Path = ALIM_GUNU_PATH) -> dict | None:
    d = _read(path)
    if not d or (d.get("onayli") is not True and not include_unapproved):
        return None
    return {"uyari": d.get("uyari", ""), "bolumler": [{"baslik": b["baslik"], "maddeler": list(b.get("maddeler") or [])}
                                                     for b in d.get("bolumler") or []]}


def validate_alim_gunu(path: Path = ALIM_GUNU_PATH) -> list[str]:
    d, errs = _read(path), []
    if not d:
        return ["alim_gunu.yaml bulunamadı ya da boş"]
    if not isinstance(d.get("onayli"), bool):
        errs.append("'onayli' true/false olmalı")
    for k in ("kaynak", "uyari"):
        if not d.get(k):
            errs.append(f"'{k}' eksik")
    for i, b in enumerate(d.get("bolumler") or []):
        if not b.get("baslik") or not b.get("maddeler"):
            errs.append(f"bölüm {i + 1}: baslik ve maddeler zorunlu")
        for m in b.get("maddeler") or []:
            if not isinstance(m, str) or len(m) > 300:
                errs.append(f"bölüm {i + 1}: madde metin olmalı ve 300 karakteri geçmemeli")
    return errs
