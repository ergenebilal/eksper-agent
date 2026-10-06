from arac_eksper.config.rules_loader import load_rules
from arac_eksper.schemas import Verdict, ListingDetail, DescriptionFindings, PartState


def round_to_5000(val: float) -> int:
    return int(round(val / 5000.0) * 5000)


def floor_to_5000(val: float) -> int:
    """Aşağı yuvarlar (küçük ek ile kayan nokta hatası 5000'in katını bir basamak düşürmesin)."""
    return int((val + 1e-6) // 5000 * 5000)


def _tl(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _pct(x: float) -> str:
    return f"%{x * 100:.1f}".replace(".0", "").replace(".", ",")


def breakdown(detail: ListingDetail, findings: DescriptionFindings, verdict: Verdict,
              allow_no_market: bool = False) -> dict | None:
    """Açıklamalı teklif hesabı. Matematik calculate_offer ile AYNIDIR (oranlar rules.yaml → teklif).
    allow_no_market=True: piyasa verisi yoksa ilan fiyatı esas alınır (kaynak="ilan"); piyasa fiyatı UYDURULMAZ,
    taban (piyasa x oran) uygulanmaz ve sonuç düşük güvenli diye işaretlenir.
    Dönüş: {kaynak, baz, hedef, acilis, ust_sinir, indirim_orani, pazarlik_payi, dayanak:[...]} ya da None."""
    if verdict.etiket == "ALINMAZ" or verdict.beklemede:
        return None
    t = load_rules()["teklif"]
    min_emsal = load_rules()["etiket"]["min_emsal"]
    az_emsal = bool(verdict.piyasa and 0 < verdict.piyasa.n < min_emsal and verdict.piyasa.medyan > 0)
    # Piyasa ancak yeterli emsal (min_emsal) varsa esas alınır; 2-3 ilanın ortalaması güvenilir bir "piyasa" değildir.
    has_market = bool(verdict.piyasa and verdict.piyasa.medyan > 0 and verdict.piyasa.n >= min_emsal)
    if not has_market and not allow_no_market:
        return None

    ilan_fiyat = detail.fiyat
    medyan = verdict.piyasa.medyan if has_market else None
    baz = min(ilan_fiyat, medyan) if has_market else ilan_fiyat
    taban = medyan * t["taban_orani"] if has_market else None

    dayanak: list[str] = []
    if has_market:
        n = verdict.piyasa.n
        dayanak.append(f"Piyasa ortalaması (ilan medyanı) {_tl(medyan)} TL, {n} emsal" +
                       (f" · ilan fiyatı ({_tl(ilan_fiyat)} TL) piyasadan yüksek: baz piyasa" if ilan_fiyat > medyan else
                        f" · baz ilan fiyatı ({_tl(ilan_fiyat)} TL)"))
    else:
        neden = (f"Emsal az (n={verdict.piyasa.n}, en az {min_emsal} gerekir): piyasa esas alınmadı" if az_emsal
                 else "Piyasa verisi yok")
        dayanak.append(f"{neden}: baz yalnızca ilan fiyatı ({_tl(ilan_fiyat)} TL). "
                       "Yeterli emsal bulunca teklif daha güvenilir olur.")

    indirim = 0.0
    sayac = {PartState.LOCAL_PAINT: [0, t["lokal_boyali"], "lokal boyalı"],
             PartState.PAINTED: [0, t["boyali"], "boyalı"], PartState.REPLACED: [0, t["degisen"], "değişen"]}
    for name, state in detail.parts.items():
        if "tampon" in name or state not in sayac:
            continue
        sayac[state][0] += 1
    for state, (adet, oran, ad) in sayac.items():
        if adet:
            indirim += adet * oran
            dayanak.append(f"{adet} {ad} parça: −{_pct(adet * oran)}")

    tramer = findings.tramer_tutari or detail.tramer_tutari_yapilandirilmis or 0
    if tramer > 0:
        oran = (tramer / baz) * t["tramer_payi"]
        indirim += oran
        dayanak.append(f"Tramer {_tl(tramer)} TL: −{_pct(oran)}")

    yas = max(detail.fetched_at.year - detail.yil, 1)
    yillik_km = detail.km / yas
    if yillik_km > t["km_orta_esik"]:
        indirim += t["km_orta_indirim"]
        dayanak.append(f"Yıllık km yüksek ({_tl(yillik_km)}): −{_pct(t['km_orta_indirim'])}")
    if yillik_km > t["km_yuksek_esik"]:
        indirim += t["km_yuksek_indirim"]
        dayanak.append(f"Yıllık km çok yüksek: −{_pct(t['km_yuksek_indirim'])}")

    if indirim > t["max_indirim"]:
        dayanak.append(f"Toplam indirim üst sınırı: −{_pct(t['max_indirim'])} (hesaplanan {_pct(indirim)})")
    indirim = min(indirim, t["max_indirim"])
    hedef = baz * (1 - indirim)

    pazarlik = t["pazarlik_dusuk_skor"] if verdict.guven_skoru < t["pazarlik_skor_esik"] else t["pazarlik_yuksek_skor"]
    dayanak.append(f"Pazarlık payı: −{_pct(pazarlik)}")

    acilis = hedef * (1 - pazarlik)
    ust = hedef
    if taban is not None:
        acilis, ust = max(acilis, taban), max(ust, taban)
        if acilis == taban:
            dayanak.append(f"Taban: piyasanın %{t['taban_orani'] * 100:.0f}'i ({_tl(taban)} TL) altına inilmez")
    acilis, ust = min(acilis, ilan_fiyat), min(ust, ilan_fiyat)       # asla ilan fiyatını aşma

    # Yuvarlama ilan fiyatının ÜSTÜNE çıkarmamalı: üst sınır/hedef aşağı yuvarlanır; açılış en yakına, ama üst sınırı geçmez.
    ust_r = floor_to_5000(ust)
    hedef_r = min(floor_to_5000(min(hedef, ilan_fiyat)), ust_r)
    acilis_r = min(round_to_5000(acilis), hedef_r)
    # Makul anlaşma noktası: açılış ile üst sınırın ortası (pazarlıkta yarı yolda buluşma)
    anlasma_r = min(max(round_to_5000((acilis_r + ust_r) / 2), acilis_r), ust_r)
    dayanak.append("Makul anlaşma noktası: açılış teklifi ile üst sınırın ortası")
    return {"kaynak": "piyasa" if has_market else "ilan", "baz": min(round_to_5000(baz), floor_to_5000(ilan_fiyat)),
            "hedef": hedef_r, "acilis": acilis_r, "anlasma": anlasma_r, "ust_sinir": ust_r,
            "indirim_orani": round(indirim, 4), "pazarlik_payi": pazarlik, "dayanak": dayanak}


def calculate_offer(detail: ListingDetail, findings: DescriptionFindings, verdict: Verdict) -> tuple[int, int] | None:
    """(açılış, üst sınır). Piyasa verisi yoksa None (kişisel araç ve karne davranışı değişmedi)."""
    b = breakdown(detail, findings, verdict, allow_no_market=False)
    return (b["acilis"], b["ust_sinir"]) if b else None
