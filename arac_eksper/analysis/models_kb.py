"""Model bilgi tabanı (config/models_kb.yaml): kronik arızalar, km eşikleri, periyodik bakım.

Kural 10 (OtoXray_Arge.md): yalnız `onayli: true` kayıtlar kararı ve listeleri etkiler; taslaklar yüklenmez.
Eşleşme: marka + model (ilan "Seri"), model yılı; maddede motor/vites/yakıt/yıl filtresi ve km eşiği olabilir.
"""
from pathlib import Path

import yaml

from arac_eksper.schemas import ListingDetail

KB_PATH = Path(__file__).parent.parent / "config" / "models_kb.yaml"
CIDDIYET = ("yuksek", "orta", "dusuk")
_FOLD = str.maketrans("çşğöüıâîûéÇŞĞÖÜİÂÎÛÉ", "csgouiaiuecsgouiaiue")


def _fold(s) -> str:
    return " ".join(str(s or "").translate(_FOLD).lower().replace("-", " ").split())


def load_kb(include_unapproved: bool = False, path: Path = KB_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        entries = (yaml.safe_load(f) or {}).get("models", []) or []
    return [e for e in entries if include_unapproved or e.get("onayli") is True]


def validate(entries: list[dict]) -> list[str]:
    """Şema hataları (CLI `arac kb kontrol` ve testler)."""
    errs = []
    for i, e in enumerate(entries):
        ad = f"#{i + 1} {e.get('marka', '?')} {e.get('model', '?')}"
        for k in ("marka", "model", "kaynak"):
            if not e.get(k):
                errs.append(f"{ad}: '{k}' eksik")
        if not isinstance(e.get("onayli"), bool):
            errs.append(f"{ad}: 'onayli' true/false olmalı")
        if e.get("yil_min") and e.get("yil_max") and e["yil_min"] > e["yil_max"]:
            errs.append(f"{ad}: yil_min > yil_max")
        for j, k in enumerate(e.get("kronik") or []):
            if not k.get("etiket") or not k.get("kontrol"):
                errs.append(f"{ad} kronik {j + 1}: etiket ve kontrol zorunlu")
            if k.get("ciddiyet", "orta") not in CIDDIYET:
                errs.append(f"{ad} kronik {j + 1}: ciddiyet {CIDDIYET} olmalı")
            if k.get("vites") not in (None, "otomatik", "manuel", "yari_otomatik"):
                errs.append(f"{ad} kronik {j + 1}: vites geçersiz")
        for j, b in enumerate(e.get("bakim") or []):
            a = b.get("aralik_km")
            if not b.get("kalem") or not (isinstance(a, list) and len(a) == 2 and 0 < a[0] <= a[1]):
                errs.append(f"{ad} bakım {j + 1}: kalem ve aralik_km [alt, üst] zorunlu")
    return errs


def _model_matches(e: dict, d: ListingDetail) -> bool:
    if _fold(e.get("marka")) != _fold(d.marka):
        return False
    if _fold(e.get("model")) not in (_fold(d.model), _fold(d.seri)):
        return False
    return not ((e.get("yil_min") and d.yil < e["yil_min"]) or (e.get("yil_max") and d.yil > e["yil_max"]))


def _text(d: ListingDetail) -> str:
    return _fold(" ".join(filter(None, [d.paket, d.motor_hacmi, d.baslik, d.vites, d.yakit])))


def _vites(d: ListingDetail) -> str | None:
    v = _fold(d.vites)
    if "yari" in v:
        return "yari_otomatik"
    if "otomatik" in v:
        return "otomatik"
    return "manuel" if "manuel" in v or "duz" in v else None


def _item_matches(k: dict, d: ListingDetail, text: str) -> bool:
    motor = k.get("motor")
    if motor:
        motors = motor if isinstance(motor, list) else [motor]
        if not any(_fold(m) in text for m in motors):
            return False
    if k.get("vites") and _vites(d) not in (None, k["vites"]):
        return False                      # vites bilinmiyorsa madde kalır (bilinmeyen "iyi" sayılmaz)
    if k.get("yakit") and d.yakit and k["yakit"] not in _fold(d.yakit):
        return False
    return not ((k.get("yil_min") and d.yil < k["yil_min"]) or (k.get("yil_max") and d.yil > k["yil_max"]))


def kronik_arizalar(detail: ListingDetail, kb: list[dict] | None = None) -> list[dict]:
    """Araca uyan kronik maddeler: etiket, kontrol, ciddiyet, km_esik, tetiklendi (km eşiği aşıldı ya da eşik yok).
    Sıra: tetiklenmiş + yüksek ciddiyet önce."""
    kb = load_kb() if kb is None else kb
    text, out = _text(detail), []
    for e in kb:
        if not _model_matches(e, detail):
            continue
        for k in e.get("kronik") or []:
            if _item_matches(k, detail, text):
                esik = k.get("km_esik")
                out.append({"etiket": k["etiket"], "kontrol": k.get("kontrol", ""), "ciddiyet": k.get("ciddiyet", "orta"),
                            "km_esik": esik, "tetiklendi": not esik or detail.km >= esik})
    rank = {"yuksek": 0, "orta": 1, "dusuk": 2}
    return sorted(out, key=lambda k: (not k["tetiklendi"], rank.get(k["ciddiyet"], 1)))


def bakim_kalemleri(detail: ListingDetail, kb: list[dict] | None = None) -> list[dict]:
    """Km'si bakım aralığına girmiş/aşmış periyodik ağır bakımlar: kalem, aralik_km, not."""
    kb = load_kb() if kb is None else kb
    text, out = _text(detail), []
    for e in kb:
        if not _model_matches(e, detail):
            continue
        for b in e.get("bakim") or []:
            if b.get("motor") and not _item_matches({"motor": b["motor"]}, detail, text):
                continue
            if detail.km >= b["aralik_km"][0]:
                out.append({"kalem": b["kalem"], "aralik_km": b["aralik_km"], "not": b.get("not", "")})
    return out


def _tl_km(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def ekspertiz_maddeleri(detail: ListingDetail, kb: list[dict] | None = None) -> list[str]:
    """Araca özel ekspertiz maddeleri (R1.2): tetiklenmiş kronikler önce, sonra bakım zamanı gelenler, sonra diğerleri."""
    kronik = kronik_arizalar(detail, kb)
    out = []
    for k in kronik:
        if k["tetiklendi"]:
            esik = f" (araç {_tl_km(detail.km)} km; risk {_tl_km(k['km_esik'])} km'den sonra artar)" if k["km_esik"] else ""
            out.append(f"{k['etiket']}: {k['kontrol']}{esik}")
    for b in bakim_kalemleri(detail, kb):
        lo, hi = b["aralik_km"]
        out.append(f"{b['kalem']}: {_tl_km(lo)}-{_tl_km(hi)} km'de yapılır; araç {_tl_km(detail.km)} km. "
                   f"Yapıldı mı sorun, faturasını isteyin.{(' ' + b['not']) if b['not'] else ''}")
    out += [f"{k['etiket']}: {k['kontrol']}" for k in kronik if not k["tetiklendi"]]
    return out
