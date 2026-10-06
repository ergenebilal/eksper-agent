from arac_eksper.config.rules_loader import load_rules
from arac_eksper.schemas import Verdict, ListingDetail, DescriptionFindings, PartState

def round_to_5000(val: float) -> int:
    return int(round(val / 5000.0) * 5000)

def calculate_offer(detail: ListingDetail, findings: DescriptionFindings, verdict: Verdict) -> tuple[int, int] | None:
    if verdict.etiket == "ALINMAZ":
        return None
        
    if not verdict.piyasa or verdict.piyasa.medyan <= 0:
        return None
        
    t = load_rules()["teklif"]
    ilan_fiyat = detail.fiyat
    medyan = verdict.piyasa.medyan
    
    baz_fiyat = min(ilan_fiyat, medyan)
    taban_fiyat = medyan * t['taban_orani']
    
    indirim_orani = 0.0
    
    # Parça indirimleri
    for name, state in detail.parts.items():
        if "tampon" in name: continue
        if state == PartState.LOCAL_PAINT: indirim_orani += t['lokal_boyali']
        elif state == PartState.PAINTED: indirim_orani += t['boyali']
        elif state == PartState.REPLACED: indirim_orani += t['degisen']
        
    # Tramer indirimi
    tramer = findings.tramer_tutari or detail.tramer_tutari_yapilandirilmis or 0
    if tramer > 0:
        indirim_orani += (tramer / baz_fiyat) * t['tramer_payi']
        
    # KM indirimi
    yas = max(detail.fetched_at.year - detail.yil, 1)
    yillik_km = detail.km / yas
    if yillik_km > t['km_orta_esik']:
        indirim_orani += t['km_orta_indirim']
    if yillik_km > t['km_yuksek_esik']:
        indirim_orani += t['km_yuksek_indirim']
        
    # Max indirim %15
    indirim_orani = min(indirim_orani, t['max_indirim'])
    
    hedef_fiyat = baz_fiyat * (1 - indirim_orani)
    
    # Güven skoru pazarlık payı (%2-4)
    pazarlik_payi = t['pazarlik_dusuk_skor'] if verdict.guven_skoru < t['pazarlik_skor_esik'] else t['pazarlik_yuksek_skor']
    
    acilis_teklifi = hedef_fiyat * (1 - pazarlik_payi)
    acilis_teklifi = max(acilis_teklifi, taban_fiyat)
    
    ust_sinir = max(hedef_fiyat, taban_fiyat)
    
    # Asla ilan fiyatını aşma
    acilis_teklifi = min(acilis_teklifi, ilan_fiyat)
    ust_sinir = min(ust_sinir, ilan_fiyat)
    
    return round_to_5000(acilis_teklifi), round_to_5000(ust_sinir)

