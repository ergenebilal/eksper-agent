import yaml
from pathlib import Path
from arac_eksper.schemas import ListingDetail, DescriptionFindings, Verdict, PartState
from arac_eksper.analysis.market import MarketStats
from arac_eksper.analysis.models_kb import kronik_arizalar

from arac_eksper.config.rules_loader import load_rules  # noqa: F401  (yeniden dışa aktarım)

def _sapma(detail: ListingDetail, market: MarketStats) -> float:
    if market and market.medyan > 0:
        return (detail.fiyat - market.medyan) / market.medyan
    return 0.0

def _yillik_km(detail: ListingDetail) -> float:
    yas = max(detail.fetched_at.year - detail.yil, 1)
    return detail.km / yas

def _bilinen_parca(detail: ListingDetail) -> int:
    return sum(1 for st in detail.parts.values() if st != PartState.UNKNOWN)


def alinir_engelleri(detail: ListingDetail, findings: DescriptionFindings) -> list[str]:
    """🟢'yi engelleyen (ama 🔴 yapmayan) durumlar: bilinmeyen ya da doğrulanamayan risk 'iyi' sayılmaz."""
    out = []
    if not _bilinen_parca(detail):
        out.append("parça diyagramı yok / parçalar bilinmiyor")
    if findings.dolandiricilik_sinyalleri:
        out.append("dolandırıcılık sinyali var")
    if findings.motor_sanziman in ("degisen", "sorunlu"):
        out.append(f"motor/şanzıman {findings.motor_sanziman}")
    if findings.km_degisimi_suphesi:
        out.append("km değişimi şüphesi")
    if findings.dogrulanamayan_iddia:
        out.append("açıklamadaki olumsuz bir iddia doğrulanamadı (alıntı yok)")
    return out


def evaluate_hard_fails(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats,
                        rules: dict, max_butce: int | None = None) -> list[str]:
    hf = rules["hard_fails"]
    fails = []

    if detail.agir_hasar_kayitli:
        fails.append("Ağır hasar kayıtlı")

    if findings.agir_hasar_beyan == "var":
        fails.append("Açıklamada pert/çekme belgeli/ağır hasar beyanı")

    if findings.sase_direk_podye_islem == "var":
        fails.append("Şase, podye veya direkte işlem var")

    if findings.airbag == "acmis":
        fails.append("Airbag açmış")

    tavan_state = detail.parts.get("tavan", PartState.UNKNOWN)
    if tavan_state.value in hf["tavan_elenen_durumlar"]:
        fails.append(f"Tavan {tavan_state.value}")

    if hf.get("butce_asimi") and max_butce is not None and detail.fiyat > max_butce:
        fails.append(f"Fiyat bütçenin üstünde ({detail.fiyat:,} > {max_butce:,} TL)".replace(",", "."))

    sapma = _sapma(detail, market)
    if sapma > hf["max_sapma"]:
        fails.append(f"Fiyat piyasanın %{sapma*100:.0f} üzerinde")

    yillik_km = _yillik_km(detail)
    if yillik_km > hf["max_yillik_km"]:
        fails.append(f"Yıllık KM çok yüksek ({yillik_km:.0f})")

    if len(findings.dolandiricilik_sinyalleri) >= 1 and sapma < hf["dolandiricilik_sapma"]:
        fails.append("Dolandırıcılık şüphesi ve aşırı düşük fiyat")

    return fails

def evaluate_score_trace(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats,
                         rules: dict, kronik: list[dict] | None = None) -> tuple[float, list[dict]]:
    """10 üzerinden skor + karar dökümü ([{kural, puan}]). `arac explain` bunu basar."""
    sc = rules["scoring"]
    bt = rules["bantlar"]
    trace: list[dict] = []

    def add(kural: str, puan: float):
        if puan != 0:
            trace.append({"kural": kural, "puan": round(puan, 2)})

    # Parçalar
    unknown_count = 0
    for name, state in detail.parts.items():
        if "tampon" in name:
            if state in [PartState.PAINTED, PartState.REPLACED]:
                add(f"{name} {state.value}", sc["tampon_boya_degisen"])
            continue
        if state == PartState.LOCAL_PAINT:
            add(f"{name} lokal boyalı", sc["lokal_boyali_parca"])
        elif state == PartState.PAINTED:
            add(f"{name} boyalı", sc["boyali_parca"])
        elif state == PartState.REPLACED:
            if "kaput" in name or "bagaj" in name:
                add(f"{name} değişen", sc["degisen_kaput_bagaj"])
            else:
                add(f"{name} değişen", sc["degisen_parca"])
        elif state == PartState.UNKNOWN:
            unknown_count += 1
    if not detail.parts:
        # Diyagram hiç yoksa hiçbir parça bilinmiyor: en yüksek "bilinmeyen parça" cezası (kural 9)
        add("Parça diyagramı yok (parçalar bilinmiyor)", -abs(sc["unknown_max"]))
    elif unknown_count:
        add(f"{unknown_count} parça belirtilmemiş",
            -min(unknown_count * abs(sc["unknown_parca"]), abs(sc["unknown_max"])))

    # Tramer: None = bilinmiyor, 0 = açıkça yok (ceza yok), >0 = orana göre
    tramer = findings.tramer_tutari if findings.tramer_tutari is not None else detail.tramer_tutari_yapilandirilmis
    if tramer is None:
        add("Tramer bilinmiyor", sc["tramer_bilinmiyor"])
    elif tramer > 0 and detail.fiyat > 0:
        oran = tramer / detail.fiyat
        key = ("tramer_0_5" if oran <= bt["tramer_orani_alt"] else "tramer_5_10" if oran <= bt["tramer_orani_ust"]
               else "tramer_10_plus")
        add(f"Tramer %{oran*100:.1f} ({tramer:,} TL)".replace(",", "."), sc[key])

    # Yıllık KM
    yillik_km = _yillik_km(detail)
    yas = max(detail.fetched_at.year - detail.yil, 1)
    if bt["yillik_km_orta"] <= yillik_km < bt["yillik_km_yuksek"]:
        add(f"Yıllık km {yillik_km:,.0f}".replace(",", "."), sc["yillik_km_25_35"])
    elif bt["yillik_km_yuksek"] <= yillik_km <= rules["hard_fails"]["max_yillik_km"]:
        add(f"Yıllık km {yillik_km:,.0f}".replace(",", "."), sc["yillik_km_35_45"])
    if yillik_km < bt["yillik_km_suphe_alt"] and yas >= bt["yillik_km_suphe_min_yas"]:
        add(f"Yıllık km çok düşük ({yillik_km:,.0f}) — km düşürme şüphesi".replace(",", "."), sc["yillik_km_suphe"])

    # Bulgular
    add(f"{len(findings.olumsuz_sinyaller)} olumsuz sinyal", len(findings.olumsuz_sinyaller) * sc["olumsuz_sinyal"])
    add(f"{len(findings.belirsiz_ifadeler)} belirsiz ifade", len(findings.belirsiz_ifadeler) * sc["belirsiz_ifade"])
    add(f"{len(findings.olumlu_sinyaller)} olumlu sinyal (beyan)",
        min(len(findings.olumlu_sinyaller) * sc["olumlu_sinyal"], sc["olumlu_max"]))

    # Fiyat avantajı
    sapma = _sapma(detail, market)
    if market and market.medyan > 0 and bt["sapma_bonus_alt"] <= sapma <= bt["sapma_bonus_ust"]:
        add(f"Fiyat piyasanın %{abs(sapma)*100:.0f} altında", sc["sapma_eksi_5_15"])

    # Model bazlı kronik arızalar
    for k in (kronik or []):
        add(f"Kronik arıza: {k.get('etiket', '?')}", sc["kronik_ariza"])

    score = max(0.0, min(10.0, 10.0 + sum(t["puan"] for t in trace)))
    return score, trace


def evaluate_score(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats,
                   rules: dict, kronik: list[dict] | None = None) -> float:
    return evaluate_score_trace(detail, findings, market, rules, kronik)[0]


def determine_verdict(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats,
                      max_butce: int | None = None, kb: list[dict] | None = None) -> Verdict:
    rules = load_rules()
    kronik = kronik_arizalar(detail, kb)

    hard_fails = evaluate_hard_fails(detail, findings, market, rules, max_butce)
    score, trace = evaluate_score_trace(detail, findings, market, rules, kronik)
    sapma = _sapma(detail, market)

    # Veri tamlığı
    tamlik = 1.0
    if not _bilinen_parca(detail):
        tamlik -= rules["tamlik"]["parca_yok"]
    if findings.tramer_tutari is None and detail.tramer_tutari_yapilandirilmis is None:
        tamlik -= rules["tamlik"]["tramer_bilinmiyor"]
    et = rules["etiket"]
    yetersiz_piyasa = not market or market.n < et["min_emsal"]
    if yetersiz_piyasa:
        tamlik -= rules["tamlik"]["piyasa_yetersiz"]
    tamlik = max(0.0, tamlik)

    engeller = alinir_engelleri(detail, findings)

    # Etiket
    if hard_fails or score < et["alinmaz_skor_alti"]:
        etiket = "ALINMAZ"
    elif (not engeller and score >= et["alinir_min_skor"] and sapma <= et["alinir_max_sapma"]
          and findings.sase_direk_podye_islem != "var"
          and tamlik >= et["alinir_min_tamlik"] and not yetersiz_piyasa):
        etiket = "ALINIR"
    else:
        etiket = "DUSUNULEBILIR"

    artilar = [s.etiket for s in findings.olumlu_sinyaller if s.etiket]
    eksiler = hard_fails.copy() + [s.etiket for s in findings.olumsuz_sinyaller if s.etiket]
    if findings.tramer_tutari:
        eksiler.append(f"{findings.tramer_tutari:,} TL Tramer".replace(",", "."))
    if market and market.medyan > 0 and sapma < rules["bantlar"]["sapma_ucuz_uyari"]:
        eksiler.append(f"Piyasadan %{abs(sapma)*100:.0f} ucuz: neden bu kadar ucuz? (gizli hasar / dolandırıcılık kontrolü)")
    if findings.km_degisimi_suphesi:
        eksiler.append("Km değişimi şüphesi (açıklamadan)")
    if findings.motor_sanziman in ("degisen", "sorunlu"):
        eksiler.append(f"Motor/şanzıman: {findings.motor_sanziman} (açıklamadan)")
    if engeller and not hard_fails:
        eksiler += [f"ALINIR engeli: {e}" for e in engeller]
    if yetersiz_piyasa:
        eksiler.append("Piyasa emsali yetersiz: fiyat karşılaştırması güvenilir değil")
    eksiler += [f"Kronik arıza: {k.get('etiket', '?')}" for k in kronik]

    kontrol = ["Şase uçları", "Podyeler", "Direkler", "Airbag modülü", "Motor üfleme testi"]
    kontrol += [k["kontrol"] for k in kronik if k.get("kontrol")]

    verdict = Verdict(
        ilan_no=detail.ilan_no, etiket=etiket, guven_skoru=round(score, 1), veri_tamlik=round(tamlik, 2),
        hard_fails=hard_fails, piyasa=market, artilar=artilar, eksiler=eksiler,
        ekspertiz_kontrol_listesi=kontrol, trace=trace,
    )

    from arac_eksper.analysis.offer import calculate_offer
    teklif = calculate_offer(detail, findings, verdict)
    if teklif:
        verdict.tavsiye_teklif, verdict.ust_sinir = teklif
    return verdict
