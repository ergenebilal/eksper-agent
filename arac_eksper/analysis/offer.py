from arac_eksper.schemas import Verdict

def round_to_5000(val: float) -> int:
    return int(round(val / 5000.0) * 5000)

def calculate_offer(verdict: Verdict) -> int | None:
    if verdict.etiket == "ALINMAZ":
        return None
        
    if not verdict.piyasa or verdict.piyasa.medyan == 0:
        return None
        
    fiyat = verdict.piyasa.medyan # gerçekte ilan detayı da girmeli, basit tuttuk
    taban = verdict.piyasa.medyan * 0.85
    
    # İndirim hesaplamaları (basit versiyon)
    indirim_orani = 0.0
    if verdict.guven_skoru < 8.0:
        indirim_orani += 0.05
    if verdict.guven_skoru < 6.5:
        indirim_orani += 0.08
        
    hedef = fiyat * (1 - indirim_orani) * 0.97 # pazarlık payı %3
    
    tavsiye = max(hedef, taban)
    return round_to_5000(tavsiye)
