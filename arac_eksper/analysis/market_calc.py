"""Saf (durumsuz) piyasa hesabı: veritabanı yok, dosya yok. Emsaller istekle birlikte GEÇİCİ olarak gelir,
hesap bellekte yapılır ve hiçbir şey saklanmaz. DB'li sürüm (market.py) kişisel kullanım aracında kalır."""
import numpy as np

from arac_eksper.config.rules_loader import load_rules
from arac_eksper.schemas import MarketStats

Comparable = tuple  # (kimlik, yıl, km, fiyat) ya da (kimlik, yıl, km, fiyat, seri)

_FOLD = str.maketrans("çşğöüı", "csgoui")


def norm_seri(s) -> str:
    s = (s or "").replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def summarize_prices(prices: list[int], guven: str) -> MarketStats:
    """IQR ile aykırı değerleri atıp medyan/çeyreklikleri döner."""
    if not prices:
        return MarketStats(n=0, medyan=0, p25=0, p75=0, guven="yok")
    q1, q3 = np.percentile(prices, 25), np.percentile(prices, 75)
    iqr = q3 - q1
    valid = [p for p in prices if q1 - 1.5 * iqr <= p <= q3 + 1.5 * iqr] or prices
    return MarketStats(n=len(valid), medyan=int(np.median(valid)), p25=int(np.percentile(valid, 25)),
                       p75=int(np.percentile(valid, 75)), guven=guven)


def stats_from_comparables(target_id: str, yil: int, km: int, comps: list[Comparable], seri: str | None = None) -> MarketStats:
    """Hedef ilanın kendisi (kimlik) emsal sayılmaz. Hedefin serisi biliniyorsa YALNIZ aynı seriden emsaller sayılır
    (farklı seri/donanım karıştırılırsa sapma yanıltır). Dar aralık yetmezse bir kez genişletilir ve güven düşer."""
    pz = load_rules()["piyasa"]
    others = [c for c in comps if c[0] != target_id]
    want = norm_seri(seri)
    if want:
        others = [c for c in others if len(c) > 4 and norm_seri(c[4]) == want]

    def pick(dy: int, share: float) -> list[int]:
        lo, hi = max(0, km - km * share), km + km * share
        return [c[3] for c in others if abs(c[1] - yil) <= dy and lo <= c[2] <= hi]

    prices, guven = pick(1, pz["dar_km_payi"]), "yuksek"
    if len(prices) < pz["dar_min_n"]:
        prices, guven = pick(2, pz["genis_km_payi"]), "dusuk"
    return summarize_prices(prices, guven)
