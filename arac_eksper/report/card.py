from arac_eksper.schemas import ListingDetail, DescriptionFindings, Verdict, PartState

def generate_markdown_card(detail: ListingDetail, findings: DescriptionFindings | None, verdict: Verdict) -> str:
    # 1. Başlık ve Etiket
    etiket_emoji = "🟢" if verdict.etiket == "ALINIR" else "🟡" if verdict.etiket == "DUSUNULEBILIR" else "🔴"
    etiket_text = f"{etiket_emoji} {verdict.etiket}"
    if verdict.beklemede:
        etiket_text = "⏳ ANALİZ BEKLİYOR (LLM erişilemedi)"
    if verdict.etiket == "ALINIR":
        etiket_text += " — ekspertize götürmeye değer"
        
    # 2. Araç Bilgisi
    arac_bilgisi = f"{detail.yil} {detail.marka} {detail.model} {detail.paket or ''} · {detail.km:,} km · {detail.il}/{detail.ilce or ''}".replace(',', '.')
    
    # 3. Fiyat ve Piyasa
    sapma_str = ""
    piyasa_str = ""
    if verdict.piyasa and verdict.piyasa.medyan > 0:
        sapma = (detail.fiyat - verdict.piyasa.medyan) / verdict.piyasa.medyan
        sapma_str = f" | {'+' if sapma > 0 else ''}%{sapma*100:.0f}"
        piyasa_str = f" | Piyasa ilan medyanı: {verdict.piyasa.medyan:,} TL (n={verdict.piyasa.n})".replace(',', '.')
    fiyat_satiri = f"Fiyat: {detail.fiyat:,} TL{piyasa_str}{sapma_str}".replace(',', '.')
    
    # 4. Güven ve Veri Tamlığı
    guven_satiri = f"Güven: {verdict.guven_skoru}/10 · Veri tamlığı: %{verdict.veri_tamlik * 100:.0f}"
    
    # 5. Artılar ve Eksiler
    artilar = verdict.artilar.copy()
    for o in (findings.olumlu_sinyaller if findings else []):
        artilar.append(f"{o.etiket} (beyan)")
        
    eksiler = verdict.eksiler.copy()
    for o in (findings.olumsuz_sinyaller if findings else []):
        eksiler.append(f"{o.etiket} (açıklamadan)")
        
    artilar_satiri = f"✅ {', '.join(artilar)}" if artilar else ""
    eksiler_satiri = f"⚠️ {', '.join(eksiler)}" if eksiler else ""
    
    # 6. Teklif
    teklif_satiri = ""
    if verdict.tavsiye_teklif:
        ust_sinir = verdict.ust_sinir or verdict.tavsiye_teklif
        teklif_satiri = f"💬 Teklif: {verdict.tavsiye_teklif:,} TL ile aç, {ust_sinir:,} TL üst sınır".replace(',', '.')
        
    # 7. Ekspertiz
    ekspertiz_satiri = "🔍 Ekspertizde mutlaka bakılacak: şase uçları, podyeler, direkler, airbag modülü"
    if verdict.ekspertiz_kontrol_listesi:
        ekspertiz_satiri += ", " + ", ".join(verdict.ekspertiz_kontrol_listesi)
        
    # 8. Link
    link_satiri = f"🔗 {detail.url}"
    
    lines = [
        etiket_text,
        arac_bilgisi,
        fiyat_satiri,
        guven_satiri,
    ]
    if artilar_satiri: lines.append(artilar_satiri)
    if eksiler_satiri: lines.append(eksiler_satiri)
    if teklif_satiri: lines.append(teklif_satiri)
    lines.append(ekspertiz_satiri)
    lines.append(link_satiri)
    
    return "\n".join(lines)
