"""Savaş Odası karşılaştırması (R3.3): 2-5 ilan → deterministik tablo + kural tabanlı seçimler + doğrulanmış anlatım.

Kararlar KODDA verilir (açıklanabilir): fiyat/performans galibi, en riskli, pazarlık şansı en yüksek, ekspertiz sırası.
LLM yalnız bu tablodan gerekçe metni yazar; tabloda olmayan SAYI ya da dil kılavuzu dışı kelime içeren cümle atılır
(kural 4-5, CyberOto_Arge.md §7). LLM yoksa şablon metin kullanılır.
"""
import re
from datetime import date

from pydantic import BaseModel

ETIKET_SIRA = {"ALINIR": 0, "DUSUNULEBILIR": 1, "ALINMAZ": 2}
ETIKET_AD = {"ALINIR": "Alınır", "DUSUNULEBILIR": "Düşünülebilir", "ALINMAZ": "Alınmaz"}
YASAK = re.compile(r"panik|fırsat|kelepir|dolandırıcı|sahtekar|alsatçı|çaresiz|kazık|enayi", re.I)


def _tl(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def satir(i: int, it: dict, bugun: date) -> dict:
    """Tek ilanın karşılaştırma satırı (yalnız istemcinin gönderdiği ve sunucunun hesapladığı sayılar)."""
    s = it["sonuc"]
    gm = it.get("gercek_maliyet") or {}
    yas = max((date.today() if bugun is None else bugun).year - it["yil"], 1)
    ilan_gun = (bugun - it["ilan_tarihi"]).days if it.get("ilan_tarihi") else None
    gorulen = it.get("gorulen_fiyatlar") or []
    dusus = (max(gorulen) - it["fiyat"]) if gorulen and max(gorulen) > it["fiyat"] else 0
    return {
        "no": i, "ilan_no": it["ilan_no"], "baslik": it.get("baslik", "")[:80], "fiyat": it["fiyat"], "yil": it["yil"],
        "km": it["km"], "yillik_km": round(it["km"] / yas), "etiket": s["etiket"], "skor": s["skor"],
        "veri_tamlik": s.get("veri_tamlik"), "hard_fail_sayi": len(s.get("hard_fails") or []),
        "hard_fails": (s.get("hard_fails") or [])[:3], "eksi_sayi": len(s.get("eksiler") or []),
        "eksiler": (s.get("eksiler") or [])[:4], "artilar": (s.get("artilar") or [])[:4],
        "sapma_yuzde": s.get("sapma_yuzde"), "maliyet_alt": gm.get("toplam_alt") or it["fiyat"],
        "maliyet_ust": gm.get("toplam_ust") or it["fiyat"], "masraf_beyan": gm.get("beyan_alt") or 0,
        "ilan_gun": ilan_gun, "fiyat_degisti": it.get("fiyat_degisti"), "gorulen_dusus": dusus,
    }


def risk_puani(r: dict) -> float:
    return (r["hard_fail_sayi"] * 3 + (3 if r["etiket"] == "ALINMAZ" else 0) + (10 - r["skor"]) / 2
            + (1 - (r["veri_tamlik"] or 0)) * 2 + min(r["eksi_sayi"], 6) * 0.3)


def pazarlik_puani(r: dict) -> float:
    p = 0.0
    if r["ilan_gun"] is not None:
        p += min(r["ilan_gun"], 90) / 30            # ilanda kaldıkça satış motivasyonu artar
    if r["fiyat_degisti"]:
        p += 1.0
    if r["gorulen_dusus"] > 0:
        p += 1.0
    if r["sapma_yuzde"] is not None and r["sapma_yuzde"] > 0:
        p += min(r["sapma_yuzde"], 30) / 10        # piyasa üstü fiyat = pay
    return p


def secimler(tablo: list[dict]) -> dict:
    adaylar = [r for r in tablo if r["etiket"] != "ALINMAZ"] or tablo
    galip = min(adaylar, key=lambda r: (ETIKET_SIRA[r["etiket"]], -r["skor"], r["maliyet_alt"]))
    riskli = max(tablo, key=risk_puani)
    pazar = max(tablo, key=pazarlik_puani)
    sira = [r["ilan_no"] for r in sorted(adaylar, key=lambda r: (ETIKET_SIRA[r["etiket"]], -r["skor"], r["maliyet_alt"]))
            if r["etiket"] != "ALINMAZ"]
    return {"galip": galip["ilan_no"], "en_riskli": riskli["ilan_no"], "pazarlik": pazar["ilan_no"], "ekspertiz_sirasi": sira}


def _r(tablo, ilan_no):
    return next(r for r in tablo if r["ilan_no"] == ilan_no)


def sablon_anlatim(tablo: list[dict], sec: dict) -> dict:
    """LLM yoksa: tablodaki sayılarla deterministik gerekçe."""
    g, k, p = _r(tablo, sec["galip"]), _r(tablo, sec["en_riskli"]), _r(tablo, sec["pazarlik"])
    galip = (f"{g['no']} numaralı ilan {ETIKET_AD[g['etiket']]} etiketi ve {g['skor']}/10 güven puanıyla öne çıkıyor; "
             f"tahmini toplam maliyeti {_tl(g['maliyet_alt'])} TL'den başlıyor.")
    neden = k["hard_fails"][0] if k["hard_fails"] else (k["eksiler"][0] if k["eksiler"] else f"güven puanı {k['skor']}/10")
    riskli = f"{k['no']} numaralı ilan en yüksek riski taşıyor: {neden}."
    pz = []
    if p["ilan_gun"] is not None:
        pz.append(f"{p['ilan_gun']} gündür yayında")
    if p["fiyat_degisti"]:
        pz.append("fiyatı daha önce değişmiş")
    if p["gorulen_dusus"]:
        pz.append(f"sizin gördüğünüz fiyattan {_tl(p['gorulen_dusus'])} TL düşmüş")
    if p["sapma_yuzde"] is not None and p["sapma_yuzde"] > 0:
        pz.append(f"piyasa ortalamasının %{p['sapma_yuzde']} üzerinde")
    pazarlik = (f"{p['no']} numaralı ilanda pazarlık payı en geniş görünüyor" + (": " + ", ".join(pz) if pz else "") + ".")
    return {"galip": galip, "en_riskli": riskli, "pazarlik": pazarlik}


class Anlatim(BaseModel):
    galip: str
    en_riskli: str
    pazarlik: str


def _formlar(v) -> set[str]:
    """Bir sayının metinde görülebilecek yazımları: 7 / 7.0 / 7,0 / 820000 / 820.000 / mutlak değer."""
    if not isinstance(v, (int, float)):
        return {str(v)}
    out = set()
    for x in {v, abs(v)}:
        out |= {str(x), f"{x:g}", f"{x:.1f}", f"{x:.1f}".replace(".", ","), f"{x:g}".replace(".", ",")}
        if float(x).is_integer():
            out |= {str(int(x)), _tl(x)}
    return out


def _izinli_sayilar(tablo: list[dict]) -> set[str]:
    out = set()
    for r in tablo:
        for k in ("no", "fiyat", "yil", "km", "yillik_km", "skor", "maliyet_alt", "maliyet_ust", "masraf_beyan",
                  "ilan_gun", "gorulen_dusus", "sapma_yuzde", "hard_fail_sayi", "eksi_sayi"):
            v = r.get(k)
            if v is None:
                continue
            out.update(_formlar(v))
        for txt in r["eksiler"] + r["artilar"] + r["hard_fails"]:
            out.update(re.findall(r"\d[\d.,]*", txt))
    return out | {"10", "100"}


def dogrula(metin: str, tablo: list[dict]) -> str:
    """Tabloda olmayan sayı ya da yasak kelime içeren cümleleri atar."""
    izin = _izinli_sayilar(tablo)
    kal = []
    for c in re.split(r"(?<=[.!?])\s+", (metin or "").strip()):
        sayilar = [n.rstrip(".,") for n in re.findall(r"\d[\d.,]*", c)]
        if YASAK.search(c) or any(n not in izin for n in sayilar if n):
            continue
        kal.append(c)
    return " ".join(kal).strip()


SISTEM = """Sen bir araç alım danışmanısın. Sana 2-5 ilanın karşılaştırma tablosu ve KODLA verilmiş kararlar (galip, en riskli,
pazarlık) veriliyor. Görevin yalnızca bu kararların GEREKÇESİNİ Türkçe, kısa (her alan en fazla 2 cümle) yazmak.
KURALLAR: Yalnızca tablodaki sayıları kullan, hesap yapma, yeni sayı üretme. İlanlara "1 numaralı ilan" gibi numarasıyla
değin. Kişiler hakkında hüküm verme; dil nesnel ve finansal olsun ("panik", "fırsat", "kelepir" gibi kelimeler YASAK).
Kararları değiştirme; galip/en riskli/pazarlık ilanları sana verilenlerdir."""


def llm_anlatim(client, tablo: list[dict], sec: dict, model_name: str | None = None) -> dict | None:
    rows = []
    for r in tablo:
        rows.append(f"{r['no']} numaralı ilan: {r['baslik']} | fiyat {_tl(r['fiyat'])} TL | {r['yil']} | {_tl(r['km'])} km | "
                    f"etiket {ETIKET_AD[r['etiket']]} | güven {r['skor']}/10 | tahmini toplam maliyet {_tl(r['maliyet_alt'])}-"
                    f"{_tl(r['maliyet_ust'])} TL | piyasa sapması {r['sapma_yuzde']}% | ilanda {r['ilan_gun']} gün | "
                    f"fiyat değişti: {'evet' if r['fiyat_degisti'] else 'hayır'} | elenme: {'; '.join(r['hard_fails']) or 'yok'} | "
                    f"eksiler: {'; '.join(r['eksiler']) or 'yok'} | artılar: {'; '.join(r['artilar']) or 'yok'}")
    no = {r["ilan_no"]: r["no"] for r in tablo}
    user = ("TABLO:\n" + "\n".join(rows) + f"\n\nKARARLAR: galip = {no[sec['galip']]} numaralı ilan; en riskli = "
            f"{no[sec['en_riskli']]} numaralı ilan; pazarlık şansı en yüksek = {no[sec['pazarlik']]} numaralı ilan.")
    out = client.parse_structured(SISTEM, user, Anlatim, model_name=model_name)
    res = {k: dogrula(getattr(out, k), tablo) for k in ("galip", "en_riskli", "pazarlik")}
    return res if all(res.values()) else None
