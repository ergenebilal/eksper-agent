import yaml
from pathlib import Path
from arac_eksper.schemas import ListingDetail, DescriptionFindings, Verdict, PartState
from arac_eksper.analysis.market import MarketStats

def load_rules():
    path = Path(__file__).parent.parent / "config" / "rules.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]

def evaluate_hard_fails(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats, rules: dict) -> list[str]:
    fails = []
    
    # agir hasar
    if detail.agir_hasar_kayitli:
        fails.append("Ağır hasar kayıtlı")
        
    # sase
    if findings.sase_direk_podye_islem == "var":
        fails.append("Şase, podye veya direkte işlem var")
        
    # airbag
    if findings.airbag == "acmis":
        fails.append("Airbag açmış")
        
    # tavan
    tavan_state = detail.parts.get("tavan", PartState.UNKNOWN)
    if tavan_state in [PartState.PAINTED, PartState.REPLACED]:
        fails.append(f"Tavan {tavan_state.value}")
        
    # sapma
    sapma = 0.0
    if market and market.medyan > 0:
        sapma = (detail.fiyat - market.medyan) / market.medyan
    if sapma > 0.25:
        fails.append(f"Fiyat piyasanın %{sapma*100:.0f} üzerinde")
        
    # yillik km
    yas = max(detail.fetched_at.year - detail.yil, 1)
    yillik_km = detail.km / yas
    if yillik_km > 45000:
        fails.append(f"Yıllık KM çok yüksek ({yillik_km:.0f})")
        
    # dolandiricilik
    if len(findings.dolandiricilik_sinyalleri) >= 1 and sapma < -0.20:
        fails.append("Dolandırıcılık şüphesi ve aşırı düşük fiyat")
        
    return fails

def evaluate_score(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats, rules: dict) -> float:
    score = 10.0
    scoring_rules = rules["scoring"]
    
    # Parçalar
    unknown_count = 0
    for name, state in detail.parts.items():
        if "tampon" in name:
            if state in [PartState.PAINTED, PartState.REPLACED]:
                score += scoring_rules["tampon_boya_degisen"]
            continue
            
        if state == PartState.LOCAL_PAINT:
            score += scoring_rules["lokal_boyali_parca"]
        elif state == PartState.PAINTED:
            score += scoring_rules["boyali_parca"]
        elif state == PartState.REPLACED:
            if "kaput" in name or "bagaj" in name:
                score += scoring_rules["degisen_kaput_bagaj"]
            else:
                score += scoring_rules["degisen_parca"]
        elif state == PartState.UNKNOWN:
            unknown_count += 1
            
    unknown_penalty = min(unknown_count * abs(scoring_rules["unknown_parca"]), abs(scoring_rules["unknown_max"]))
    score -= unknown_penalty
    
    # Tramer
    tramer = findings.tramer_tutari or detail.tramer_tutari_yapilandirilmis
    if tramer and detail.fiyat > 0:
        oran = tramer / detail.fiyat
        if oran <= 0.05:
            score += scoring_rules["tramer_0_5"]
        elif oran <= 0.10:
            score += scoring_rules["tramer_5_10"]
        else:
            score += scoring_rules["tramer_10_plus"]
    else:
        score += scoring_rules["tramer_bilinmiyor"]
        
    # Yıllık KM
    yas = max(detail.fetched_at.year - detail.yil, 1)
    yillik_km = detail.km / yas
    if 25000 <= yillik_km < 35000:
        score += scoring_rules["yillik_km_25_35"]
    elif 35000 <= yillik_km <= 45000:
        score += scoring_rules["yillik_km_35_45"]
        
    if yillik_km < 4000 and yas >= 5:
        score += scoring_rules["yillik_km_suphe"]
        
    # Bulgular
    score += len(findings.olumsuz_sinyaller) * scoring_rules["olumsuz_sinyal"]
    score += len(findings.belirsiz_ifadeler) * scoring_rules["belirsiz_ifade"]
    
    olumlu_score = min(len(findings.olumlu_sinyaller) * scoring_rules["olumlu_sinyal"], scoring_rules["olumlu_max"])
    score += olumlu_score
    
    # Sapma
    if market and market.medyan > 0:
        sapma = (detail.fiyat - market.medyan) / market.medyan
        if -0.15 <= sapma <= -0.05:
            score += scoring_rules["sapma_eksi_5_15"]
            
    return max(0.0, min(10.0, score))

def determine_verdict(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats) -> Verdict:
    rules = load_rules()
    
    hard_fails = evaluate_hard_fails(detail, findings, market, rules)
    score = evaluate_score(detail, findings, market, rules)
    
    sapma = 0.0
    if market and market.medyan > 0:
        sapma = (detail.fiyat - market.medyan) / market.medyan
        
    # Veri tamlık
    tamlik = 1.0
    if not detail.parts: tamlik -= 0.3
    if not findings.tramer_tutari and not detail.tramer_tutari_yapilandirilmis: tamlik -= 0.1
    if market and market.n < 8: tamlik -= 0.2
    tamlik = max(0.0, tamlik)
    
    # Etiket
    if hard_fails or score < 5.5:
        etiket = "ALINMAZ"
    elif score >= 7.5 and sapma <= 0 and findings.sase_direk_podye_islem != "var" and tamlik >= 0.6:
        etiket = "ALINIR"
    else:
        etiket = "DUSUNULEBILIR"
        
    return Verdict(
        ilan_no=detail.ilan_no,
        etiket=etiket,
        guven_skoru=round(score, 1),
        veri_tamlik=round(tamlik, 2),
        hard_fails=hard_fails,
        piyasa=market
    )
