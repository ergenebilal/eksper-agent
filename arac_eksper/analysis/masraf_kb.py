"""Masraf bilgi tabanı (config/masraf_kb.yaml, R2.1): kalem → segment bazlı TL aralığı.

Kural 5: LLM tutar uydurmaz; tutar yalnız buradan, ARALIK olarak gelir. Kural 10: yalnız `onayli: true` kalemler kullanılır.
Segment: parça/işçilik fiyat düzeyi (ekonomik | orta | ust | premium); bilinmeyen araçta geniş aralık + "bilinmiyor".
"""
from datetime import date
from pathlib import Path

import yaml

KB_PATH = Path(__file__).parent.parent / "config" / "masraf_kb.yaml"
SEGMENTLER = ("ekonomik", "orta", "ust", "premium")
ESKIME_AY = 6
_FOLD = str.maketrans("çşğöüıâîûéÇŞĞÖÜİÂÎÛÉ", "csgouiaiuecsgouiaiue")


def _fold(s) -> str:
    return " ".join(str(s or "").translate(_FOLD).lower().replace("-", " ").split())


def load(path: Path = KB_PATH) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def kalemler(include_unapproved: bool = False, path: Path = KB_PATH) -> dict[str, dict]:
    return {k["kod"]: k for k in load(path).get("kalemler") or [] if include_unapproved or k.get("onayli") is True}


def segment(marka: str | None, seri: str | None, kb: dict | None = None) -> str:
    kb = load() if kb is None else kb
    m, s = _fold(marka), _fold(seri)
    for seg in ("ust", "orta", "ekonomik"):            # aynı model iki segmentteyse üstteki kazanır (temkinli)
        if any(_fold(a) == m and _fold(b) == s for a, b in (kb.get("segmentler") or {}).get(seg) or []):
            return seg
    if any(_fold(p) == m for p in kb.get("premium_markalar") or []):
        return "premium"
    return "bilinmiyor"


def aralik(kod: str, seg: str, kalem_map: dict[str, dict] | None = None) -> tuple[int, int] | None:
    """Onaylı kalemin TL aralığı; segment bilinmiyorsa ekonomik alt - üst segment üst sınırı (geniş, temkinli)."""
    k = (kalemler() if kalem_map is None else kalem_map).get(kod)
    if not k:
        return None
    a = k["aralik"]
    if seg in a:
        return tuple(a[seg])
    return (a["ekonomik"][0], a["ust"][1])


def validate(path: Path = KB_PATH, today: date | None = None) -> tuple[list[str], list[str]]:
    """(hatalar, uyarılar)."""
    d, errs, warns = load(path), [], []
    if not d:
        return ["masraf_kb.yaml bulunamadı ya da boş"], []
    for k in ("para_birimi", "fiyat_tarihi", "kaynak"):
        if not d.get(k):
            errs.append(f"'{k}' eksik")
    try:
        y, mo = map(int, str(d.get("fiyat_tarihi", "0-0")).split("-"))
        t = today or date.today()
        if (t.year - y) * 12 + (t.month - mo) > ESKIME_AY:
            warns.append(f"fiyat_tarihi {d['fiyat_tarihi']}: {ESKIME_AY} aydan eski, aralıkları güncelleyin")
    except ValueError:
        errs.append("fiyat_tarihi YYYY-AA olmalı")
    kodlar = set()
    for i, k in enumerate(d.get("kalemler") or []):
        ad = f"kalem {i + 1} ({k.get('kod', '?')})"
        if not k.get("kod") or not k.get("ad"):
            errs.append(f"{ad}: kod ve ad zorunlu")
        if k.get("kod") in kodlar:
            errs.append(f"{ad}: kod tekrar ediyor")
        kodlar.add(k.get("kod"))
        if not isinstance(k.get("onayli"), bool):
            errs.append(f"{ad}: onayli true/false olmalı")
        if not k.get("anahtar_kelimeler"):
            errs.append(f"{ad}: anahtar_kelimeler boş")
        a = k.get("aralik") or {}
        for seg in SEGMENTLER:
            v = a.get(seg)
            if not (isinstance(v, list) and len(v) == 2 and 0 < v[0] <= v[1]):
                errs.append(f"{ad}: aralik.{seg} [alt, üst] olmalı (0 < alt ≤ üst)")
        if all(isinstance(a.get(s), list) and len(a[s]) == 2 for s in SEGMENTLER):
            alts = [a[s][0] for s in SEGMENTLER]
            if alts != sorted(alts):
                warns.append(f"{ad}: alt sınırlar segment sırasıyla artmıyor (ekonomik ≤ orta ≤ üst ≤ premium)")
    return errs, warns
