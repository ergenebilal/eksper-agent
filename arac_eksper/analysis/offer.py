from arac_eksper.schemas import Verdict, ListingDetail, DescriptionFindings, PartState

def round_to_5000(val: float) -> int:
    return int(round(val / 5000.0) * 5000)

def calculate_offer(detail: ListingDetail, findings: DescriptionFindings, verdict: Verdict) -> tuple[int, int] | None:
    if verdict.etiket == "ALINMAZ":
        return None
        
    if not verdict.piyasa or verdict.piyasa.medyan <= 0:
        return None
        
    ilan_fiyat = detail.fiyat
    medyan = verdict.piyasa.medyan
    
    baz_fiyat = min(ilan_fiyat, medyan)
    taban_fiyat = medyan * 0.85
    
    indirim_orani = 0.0
    
    # Parça indirimleri
    for name, state in detail.parts.items():
        if "tampon" in name: continue
        if state == PartState.LOCAL_PAINT: indirim_orani += 0.01
        elif state == PartState.PAINTED: indirim_orani += 0.02
        elif state == PartState.REPLACED: indirim_orani += 0.04
        
    # Tramer indirimi
    tramer = findings.tramer_tutari or detail.tramer_tutari_yapilandirilmis or 0
    if tramer > 0:
        indirim_orani += (tramer / baz_fiyat) * 0.5
        
    # KM indirimi
    yas = max(detail.fetched_at.year - detail.yil, 1)
    yillik_km = detail.km / yas
    if yillik_km > 25000:
        indirim_orani += 0.02
    if yillik_km > 35000:
        indirim_orani += 0.03
        
    # Max indirim %15
    indirim_orani = min(indirim_orani, 0.15)
    
    hedef_fiyat = baz_fiyat * (1 - indirim_orani)
    
    # Güven skoru pazarlık payı (%2-4)
    pazarlik_payi = 0.04 if verdict.guven_skoru < 7.0 else 0.02
    
    acilis_teklifi = hedef_fiyat * (1 - pazarlik_payi)
    acilis_teklifi = max(acilis_teklifi, taban_fiyat)
    
    ust_sinir = max(hedef_fiyat, taban_fiyat)
    
    # Asla ilan fiyatını aşma
    acilis_teklifi = min(acilis_teklifi, ilan_fiyat)
    ust_sinir = min(ust_sinir, ilan_fiyat)
    
    return round_to_5000(acilis_teklifi), round_to_5000(ust_sinir)

