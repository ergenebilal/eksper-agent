"""Satıcı tarafı sinyaller (R4.1 + R4.2): satış motivasyonu bandı ve ticari dil sinyali. LLM'siz, kural tabanlı.

Dil kılavuzu (OtoXray_Arge.md §7): kişi hakkında hüküm verilmez; yalnızca ilan METNİ ve ilan VERİSİ (yayın süresi, fiyat
değişimi) sinyal olarak raporlanır. 0-100 skor yok: üç bant (düşük / orta / yüksek), her neden alıntılı ya da veriye dayalı.
İfade listeleri `config/sinyaller.yaml`, eşikler ve teklif etkisi `rules.yaml` (kural 7).
"""
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from arac_eksper.analysis.masraf import _NEG, _fold, _kw_tokens, _tokens
from arac_eksper.config.rules_loader import load_rules

PATH = Path(__file__).parent.parent / "config" / "sinyaller.yaml"
BANT_AD = {"dusuk": "Düşük", "orta": "Orta", "yuksek": "Yüksek"}
_NEG_AFTER = _NEG | {"yoktur", "yok", "degil", "degildir", "olmadan", "etmiyorum", "etmiyoruz"}


@lru_cache(maxsize=1)
def _load(path: str = str(PATH)) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _uyar(tok: str, kalip: str) -> bool:
    return tok.startswith(kalip[:-1]) if kalip.endswith("*") else tok == kalip


def _bul(text: str, ifade: str) -> str | None:
    """İfade metinde olumsuzlanmadan geçiyorsa orijinal metindeki birebir hali, yoksa None.
    Kelimeler TAM eşleşir; '*' ile biten kelime önek eşleşir."""
    toks = _tokens(text)
    kt = _kw_tokens(ifade) + (["*"] if ifade.endswith("*") else [])
    if kt[-1] == "*":
        kt = kt[:-2] + [kt[-2] + "*"]
    for i in range(len(toks) - len(kt) + 1):
        if not all(_uyar(toks[i + n][0], kt[n]) for n in range(len(kt))):
            continue
        last = i + len(kt) - 1
        sonra = [toks[x][0] for x in range(last + 1, min(len(toks), last + 3))]
        if any(s in _NEG_AFTER for s in sonra):
            continue
        return text[toks[i][1]:toks[last][2]]          # yalnız eşleşen kelimeler: alıntılar birbirini tekrar etmez
    return None


def satis_motivasyonu(text: str, ilan_tarihi: date | None = None, fiyat_degisti: bool | None = None,
                      gorulen_dusus: int = 0, bugun: date | None = None, rules: dict | None = None) -> dict:
    """{bant, ad, puan, nedenler:[{etiket, alinti|None, kaynak: metin|veri}], indirim_ivmesi: bool}"""
    r = (rules or load_rules())["sinyal"]
    nedenler, puan, gorulen = [], 0, set()
    for s in _load().get("aciliyet") or []:
        if s["etiket"] in gorulen:
            continue
        a = _bul(text or "", s["ifade"])
        if a:
            gorulen.add(s["etiket"])
            puan += s["puan"]
            nedenler.append({"etiket": s["etiket"], "alinti": a, "kaynak": "metin"})
    if ilan_tarihi:
        gun = ((bugun or date.today()) - ilan_tarihi).days
        if gun >= r["ilan_gun_uzun"]:
            puan += 2
            nedenler.append({"etiket": f"{gun} gündür yayında", "alinti": None, "kaynak": "veri"})
        elif gun >= r["ilan_gun_orta"]:
            puan += 1
            nedenler.append({"etiket": f"{gun} gündür yayında", "alinti": None, "kaynak": "veri"})
    if fiyat_degisti:
        puan += r["fiyat_degisti_puan"]
        nedenler.append({"etiket": "Fiyatı daha önce değiştirilmiş (sitenin bilgisi)", "alinti": None, "kaynak": "veri"})
    if gorulen_dusus and gorulen_dusus > 0:
        puan += r["gorulen_dusus_puan"]
        nedenler.append({"etiket": f"Sizin gördüğünüz fiyattan {gorulen_dusus:,} TL düşmüş".replace(",", "."),
                         "alinti": None, "kaynak": "veri"})
    bant = "yuksek" if puan >= r["aciliyet_yuksek"] else "orta" if puan >= r["aciliyet_orta"] else "dusuk"
    return {"bant": bant, "ad": f"Hızlı satış motivasyonu: {BANT_AD[bant].lower()}", "puan": puan, "nedenler": nedenler,
            "indirim_ivmesi": bool(fiyat_degisti and gorulen_dusus and gorulen_dusus > 0)}


def ticari_dil(text: str, kimden: str | None = None, rules: dict | None = None) -> dict | None:
    """Metinde ticari satıcı dili. Satıcı türü zaten galeri/yetkili ise "beyan" (sinyal değil, bilgi).
    Dönüş None (yok) ya da {durum: sinyal|beyan, alintilar:[...], mesaj}."""
    r = (rules or load_rules())["sinyal"]
    alintilar = []
    for ifade in _load().get("ticari") or []:
        a = _bul(text or "", ifade)
        if a and a not in alintilar:
            alintilar.append(a)
    kim = _fold(kimden or "")
    if kim and "sahibinden" not in kim:
        return {"durum": "beyan", "alintilar": alintilar[:5],
                "mesaj": f"Satıcı türü: {kimden}. Ticari satışta fatura ve ayıplı mal sorumluluğu satıcıdadır; faturayı isteyin."}
    if len(alintilar) < r["ticari_min_ifade"]:
        return None
    return {"durum": "sinyal", "alintilar": alintilar[:5],
            "mesaj": "İlan bireysel olarak yayınlanmış ama metinde ticari satış dili var."}


def soru(td: dict | None) -> dict | None:
    """Ticari dil sinyali → soru çarşafı maddesi (öncelik 1: alımın hukuki niteliğini belirler)."""
    if not td or td["durum"] != "sinyal":
        return None
    return {"oncelik": 1, "kaynak": "ticari",
            "soru": "Araç sizin adınıza mı kayıtlı? Satış sizden mi, bir firmadan mı yapılacak? Fatura kesilecek mi?",
            "neden": "İlan bireysel olarak yayınlanmış ama metinde ticari satış ifadeleri var: "
                     + ", ".join(f"“{a}”" for a in td["alintilar"][:3]) + ".",
            "cevap_ise": "Firma üzerinden satılıyorsa fatura isteyin; ruhsat sahibi ile satıcı farklıysa noterde kimin "
                         "satış yapacağını önceden netleştirin."}


def teklife_uygula(b: dict | None, sm: dict | None, rules: dict | None = None) -> dict | None:
    """Satış motivasyonu orta/yüksekse açılış teklifi ayrıca biraz aşağı çekilir (rules.yaml); üst sınır değişmez."""
    if not b or not sm or sm["bant"] == "dusuk":
        return b
    from arac_eksper.analysis.offer import floor_to_5000, round_to_5000
    t = (rules or load_rules())["teklif"]
    ek = t["aciliyet_ek_yuksek"] if sm["bant"] == "yuksek" else t["aciliyet_ek_orta"]
    yeni = floor_to_5000(b["acilis"] - b["hedef"] * ek)
    if yeni >= b["acilis"]:
        return b
    b["acilis"] = max(yeni, 0)
    b["anlasma"] = min(max(round_to_5000((b["acilis"] + b["ust_sinir"]) / 2), b["acilis"]), b["ust_sinir"])
    b["dayanak"].append(f"{sm['ad'][0].upper()}{sm['ad'][1:]}: açılış ek −%{ek * 100:g}".replace(".", ","))
    return b
