"""Likidite (piyasa hızı) v0 — R4.3. Gün sayısı SÖYLENMEZ (satış süresi verisi yok): yalnız hızlı / orta / yavaş bandı.

İki kaynak, ayrı gösterilir:
  1. Bilgi tabanı (`config/likidite_kb.yaml`, kural 10: yalnız onaylı kurallar) → bant + gerekçe.
  2. Kullanıcının kendi verisi: tarayıcısında biriken aynı seri emsal sayısı → yalnız bilgi notu (yayın süresi
     satış motivasyonu sinyalinde gösterilir)
     (bandı değiştirmez; v1'de geri bildirimle kalibre edilir).
"""
import re
from datetime import date
from pathlib import Path

import yaml

from arac_eksper.analysis import masraf_kb
from arac_eksper.analysis.masraf_kb import _fold

KB_PATH = Path(__file__).parent.parent / "config" / "likidite_kb.yaml"
BANTLAR = ("hizli", "orta", "yavas")
BANT_AD = {"hizli": "Hızlı", "orta": "Orta", "yavas": "Yavaş"}


def load(path: Path = KB_PATH) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def kurallar(include_unapproved: bool = False, path: Path = KB_PATH) -> list[dict]:
    return [k for k in load(path).get("kurallar") or [] if include_unapproved or k.get("onayli") is True]


def _cc(motor_hacmi: str | None) -> int | None:
    """'1461 cm3' → 1461; '1301 - 1600 cm3' → 1301 (aralığın ALT sınırı: temkinli)."""
    m = re.search(r"\d{3,4}", (motor_hacmi or "").replace(".", ""))
    return int(m.group(0)) if m else None


def _icerir(alan: str | None, kelimeler: list[str]) -> bool:
    a = _fold(alan)
    return bool(a) and any(_fold(k) in a for k in kelimeler)


def eslesen(d: dict, kural_listesi: list[dict], bugun: date | None = None) -> dict | None:
    """d: {marka, seri, yakit, vites, kasa_tipi, motor_hacmi, yil}"""
    seg = masraf_kb.segment(d.get("marka"), d.get("seri"))
    yas = (bugun or date.today()).year - (d.get("yil") or 0)
    for k in kural_listesi:
        c = k.get("kosul") or {}
        if "segment" in c and seg not in c["segment"]:
            continue
        if "yakit" in c and not _icerir(d.get("yakit"), c["yakit"]):
            continue
        if "vites" in c and not _icerir(d.get("vites"), c["vites"]):
            continue
        if "kasa" in c and not _icerir(d.get("kasa_tipi"), c["kasa"]):
            continue
        if "motor_cc_min" in c and not ((_cc(d.get("motor_hacmi")) or 0) > c["motor_cc_min"]):
            continue
        if "yas_min" in c and not (d.get("yil") and yas >= c["yas_min"]):
            continue
        return k
    return None


def likidite(d: dict, emsal_n: int | None = None, ilan_tarihi: date | None = None, bugun: date | None = None,
             kural_listesi: list[dict] | None = None) -> dict:
    """{bant|None, ad, gerekce|None, notlar:[...], onay_bekliyor: bool}. Onaylı kural eşleşmezse bant None."""
    onayli = kurallar() if kural_listesi is None else kural_listesi
    k = eslesen(d, onayli, bugun)
    taslak = None if k else eslesen(d, kurallar(include_unapproved=True), bugun) if kural_listesi is None else None
    notlar = []
    if emsal_n is not None:
        if emsal_n >= 30:
            notlar.append(f"Tarayıcınızda bu seriden {emsal_n} ilan birikti: arz geniş, alıcı seçici olabilir.")
        elif emsal_n >= 5:
            notlar.append(f"Tarayıcınızda bu seriden {emsal_n} ilan var.")
        elif emsal_n > 0:
            notlar.append(f"Tarayıcınızda bu seriden yalnız {emsal_n} ilan var: piyasa yorumu sınırlı.")
    return {"bant": k["bant"] if k else None, "ad": f"Piyasa hızı: {BANT_AD[k['bant']].lower()}" if k else None,
            "gerekce": k["gerekce"] if k else None, "notlar": notlar,
            "onay_bekliyor": bool(taslak), "uyari": "Satış süresi tahmini değildir; genel piyasa gözlemidir."}


def validate(path: Path = KB_PATH) -> tuple[list[str], list[str]]:
    d, errs = load(path), []
    if not d:
        return ["likidite_kb.yaml bulunamadı ya da boş"], []
    if not d.get("kaynak"):
        errs.append("kaynak alanı eksik")
    seen = set()
    for k in d.get("kurallar") or []:
        kod = k.get("kod")
        if not kod or kod in seen:
            errs.append(f"kural kodu eksik ya da tekrar: {kod}")
        seen.add(kod)
        if k.get("bant") not in BANTLAR:
            errs.append(f"{kod}: bant {BANTLAR} içinden olmalı")
        if not k.get("gerekce"):
            errs.append(f"{kod}: gerekçe eksik")
        if not isinstance(k.get("onayli"), bool):
            errs.append(f"{kod}: onayli true/false olmalı")
        bilinmeyen = set(k.get("kosul") or {}) - {"segment", "yakit", "vites", "kasa", "motor_cc_min", "yas_min"}
        if bilinmeyen:
            errs.append(f"{kod}: bilinmeyen koşul {sorted(bilinmeyen)}")
        if any(re.search(r"\d+\s*gün", k.get("gerekce") or "") for _ in [0]):
            errs.append(f"{kod}: gerekçede gün sayısı olmamalı")
    onaysiz = sum(1 for k in d.get("kurallar") or [] if k.get("onayli") is not True)
    return errs, ([f"{onaysiz} kural onay bekliyor"] if onaysiz else [])
