"""Araca özel ekspertiz listesi (R1.2) ve satıcıya sorulacaklar / soru çarşafı (R1.4). LLM'siz, deterministik.

Her madde bir kaynağa bağlıdır (izlenebilirlik): sema | bulgu | kronik | bakim | veri | piyasa | genel.
Sorular öncelik sırasıyla: 1 eleyici (şase/tavan/airbag/ağır hasar/tramer) → 2 maliyetli (bakım, kronik, motor) → 3 pazarlık.
Dil kılavuzu (CyberOto_Arge.md §7): nesnel, finansal/analitik; kişi hakkında hüküm yok.
"""
from arac_eksper.analysis.models_kb import bakim_kalemleri, kronik_arizalar
from arac_eksper.schemas import DescriptionFindings, ListingDetail, MarketStats, PartState

GENEL = ["Şase uçları", "Podyeler", "Direkler", "Airbag modülü", "Motor üfleme testi"]
_AD = {"on_tampon": "ön tampon", "arka_tampon": "arka tampon", "motor_kaputu": "motor kaputu", "bagaj_kapagi": "bagaj kapağı",
       "tavan": "tavan", "sol_on_camurluk": "sol ön çamurluk", "sag_on_camurluk": "sağ ön çamurluk",
       "sol_arka_camurluk": "sol arka çamurluk", "sag_arka_camurluk": "sağ arka çamurluk", "sol_on_kapi": "sol ön kapı",
       "sag_on_kapi": "sağ ön kapı", "sol_arka_kapi": "sol arka kapı", "sag_arka_kapi": "sağ arka kapı"}


def _km(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _parca(name: str) -> str:
    return _AD.get(name, name.replace("_", " "))


def ekspertiz_bolumleri(detail: ListingDetail, findings: DescriptionFindings, kb: list[dict] | None = None,
                        sema_uyari: str | None = None, beyan_orijinal: bool = False) -> dict:
    """{"bu_aracta": [{madde, kaynak}], "genel": [str]} — bu_aracta öncelik sıralı."""
    out: list[dict] = []
    add = lambda madde, kaynak: out.append({"madde": madde, "kaynak": kaynak})

    if sema_uyari:
        add("Tüm panellerde boya kalınlığı (mikron) ölçümü: hasar şeması 'tamamı orijinal' diyor ama ilan metniyle çelişiyor", "sema")
    elif beyan_orijinal:
        add("Tüm panellerde boya kalınlığı (mikron) ölçümü: hasar şemasındaki 'tamamı orijinal' bilgisi satıcı beyanıdır", "sema")
    degisen = [_parca(n) for n, s in detail.parts.items() if PartState(s) == PartState.REPLACED]
    if degisen:
        add(f"Değişen parçaların ({', '.join(degisen)}) bağlantı noktalarında şase/podye etkisi ve kaynak izi kontrolü", "sema")

    if findings.sase_direk_podye_islem == "var":
        add("Şase ölçümü (cihazla) ve işlemli bölgenin tespiti: açıklamada şase/podye/direk işlemi beyan edilmiş", "bulgu")
    if findings.airbag == "acmis":
        add("Airbag sistem arıza kaydı (cihazla), torpido ve direksiyon değişim izleri", "bulgu")
    if findings.motor_sanziman in ("degisen", "sorunlu"):
        add("Motor kompresyon ve üfleme testi; motor değiştiyse ruhsattaki motor numarası ile karşılaştırma", "bulgu")
    if findings.km_degisimi_suphesi:
        add("Kilometre doğrulaması: servis kayıtları ve muayene geçmişindeki km ile karşılaştırma", "bulgu")
    if findings.tramer_tutari:
        add(f"Tramer kaydındaki ({_km(findings.tramer_tutari)} TL) hasarın hangi parçalara ait olduğunun ekspertizle eşleştirilmesi", "bulgu")
    for e in findings.belirsiz_ifadeler[:2]:
        add(f"Açıklamadaki belirsiz ifade: “{e.alinti}” — neyi kastettiği ekspertizde netleştirilmeli", "bulgu")
    if detail.yakit and "lpg" in detail.yakit.lower():
        add("LPG sistemi: ruhsata işli mi, tüp test tarihi ve supap durumu", "bulgu")

    kronik = kronik_arizalar(detail, kb)
    for k in kronik:
        if k["tetiklendi"]:
            esik = f" (araç {_km(detail.km)} km; risk {_km(k['km_esik'])} km'den sonra artar)" if k["km_esik"] else ""
            add(f"{k['etiket']}: {k['kontrol']}{esik}", "kronik")
    for b in bakim_kalemleri(detail, kb):
        lo, hi = b["aralik_km"]
        add(f"{b['kalem']}: {_km(lo)}-{_km(hi)} km'de yapılır; araç {_km(detail.km)} km. Yapıldıysa faturası istenmeli", "bakim")
    for k in kronik:
        if not k["tetiklendi"]:
            add(f"{k['etiket']}: {k['kontrol']}", "kronik")
    return {"bu_aracta": out, "genel": list(GENEL)}


def soru_carsafi(detail: ListingDetail, findings: DescriptionFindings, market: MarketStats | None = None,
                 kb: list[dict] | None = None, sema_uyari: str | None = None, sapma: float | None = None) -> list[dict]:
    """Satıcıya sorulacaklar: [{soru, neden, cevap_ise, oncelik(1-3), kaynak}] öncelik sıralı, en fazla 10."""
    q: list[dict] = []
    add = lambda oncelik, kaynak, soru, neden, cevap_ise: q.append(
        {"oncelik": oncelik, "kaynak": kaynak, "soru": soru, "neden": neden, "cevap_ise": cevap_ise})

    # 1 — eleyici
    bilinen = [s for s in detail.parts.values() if PartState(s) != PartState.UNKNOWN]
    if sema_uyari or not bilinen:
        add(1, "sema", "Hangi parçalar boyalı ya da değişen? Tavan ve direklerde işlem var mı?",
            "İlandaki hasar şeması doldurulmamış ya da ilan metniyle çelişiyor.",
            "Tavan, direk ya da çok sayıda değişen parça söylenirse ekspertize gitmeden fiyatı yeniden değerlendirin.")
    if findings.sase_direk_podye_islem == "belirsiz":
        add(1, "veri", "Şase uçları, podye ve direklerde herhangi bir işlem var mı?",
            "Açıklamada yapısal parçalar hakkında bilgi yok.",
            "'Var' ya da kaçamak bir cevap gelirse bu ilan için ekspertiz masrafı yapmadan önce düşünün.")
    if findings.airbag == "belirsiz":
        add(1, "veri", "Airbag hiç açtı mı, değişti mi?", "Açıklamada airbag bilgisi yok.",
            "Açtıysa önden ciddi darbe almış demektir; şase ölçümü şart olur.")
    if detail.agir_hasar_kayitli is None and findings.agir_hasar_beyan == "belirsiz":
        add(1, "veri", "Araçta ağır hasar kaydı (pert) var mı?", "İlanda ağır hasar bilgisi okunamadı.",
            "Varsa piyasa değeri belirgin şekilde düşer; fiyat buna göre olmalı.")
    if findings.tramer_tutari is None and detail.tramer_tutari_yapilandirilmis is None:
        add(1, "veri", "Hasar kaydı (tramer) toplamı ne kadar? Sorgu ekran görüntüsünü paylaşabilir misiniz?",
            "İlanda tramer tutarı yok; araç değerinin önemli bir göstergesi.",
            "Tutar araç değerinin %10'unu aşıyorsa ya da ekran görüntüsü paylaşılmıyorsa fiyatı yeniden konuşun.")

    # 2 — maliyetli
    for b in bakim_kalemleri(detail, kb)[:2]:
        add(2, "bakim", f"{b['kalem']} yapıldı mı? Faturası var mı?",
            f"Araç {_km(detail.km)} km; bu bakım {_km(b['aralik_km'][0])}-{_km(b['aralik_km'][1])} km aralığında yapılır.",
            "Yapılmadıysa yakın vadeli masraf olarak teklifinizden düşün.")
    for k in [k for k in kronik_arizalar(detail, kb) if k["tetiklendi"]][:2]:
        add(2, "kronik", f"{k['etiket']} ile ilgili bir şikâyet ya da onarım oldu mu?",
            f"Bu model ve km için bilinen risk: {k['kontrol']}",
            "Onarım yapıldıysa faturasını isteyin; şikâyet varsa ekspertizde özellikle test ettirin.")
    if findings.motor_sanziman == "belirsiz" and detail.km >= 150_000:
        add(2, "veri", "Motor ve şanzımanda bugüne kadar hangi büyük onarımlar yapıldı?",
            f"Araç {_km(detail.km)} km ve açıklamada mekanik bilgi yok.",
            "Büyük onarım varsa belgelerini isteyin; hiç bakım bilgisi yoksa masraf payı ayırın.")
    for e in findings.belirsiz_ifadeler[:2]:
        add(2, "bulgu", f"Açıklamada “{e.alinti}” yazıyor; tam olarak ne kastediliyor?",
            "Belirsiz ifade maliyetli bir kusuru gizliyor olabilir.",
            "Somut bir cevap alamazsanız bunu masraf payı olarak düşünün.")
    if findings.km_degisimi_suphesi:
        add(2, "bulgu", "Kilometreyi servis ya da muayene kayıtlarıyla gösterebilir misiniz?",
            "Açıklamada kilometreyle ilgili şüpheli bir ifade var.",
            "Gösterilemiyorsa km'ye dayalı fiyatlama güvenilir değildir.")

    # 3 — pazarlık
    if sapma is not None and market and market.n >= 5:
        if sapma > 0.05:
            add(3, "piyasa", "Fiyatta pazarlık payı var mı?",
                f"İlan fiyatı benzer ilanların ortalamasından %{sapma * 100:.0f} yukarıda.",
                "Pazarlık payı yoksa benzer ilanlara bakmaya devam edin.")
        elif sapma < -0.20:
            add(3, "piyasa", "Fiyatın piyasanın belirgin şekilde altında olmasının nedeni nedir?",
                f"İlan fiyatı benzer ilanların ortalamasından %{abs(sapma) * 100:.0f} aşağıda.",
                "Açık ve doğrulanabilir bir neden yoksa dikkatli olun; aracı görmeden ödeme yapmayın.")
    q.sort(key=lambda x: x["oncelik"])
    return q[:10]


def soru_metni(sorular: list[dict]) -> str:
    """Kopyalanacak düz metin (satıcıya göndermeyi kullanıcı yapar)."""
    return "\n".join(f"{i}. {s['soru']}" for i, s in enumerate(sorular, 1))
