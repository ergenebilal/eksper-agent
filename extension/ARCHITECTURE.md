# Chrome Eklentisi — Mimari ve Gözden Geçirme

Orijinal taslağın (MV3 eklenti + FastAPI) ana fikri korundu: analiz motoru sunucuda kalır, eklenti yalnızca
**ilan sayfasını okur, sonucu gösterir**. Aşağıda taslakta değiştirilen/eklenen noktalar ve nedenleri var.

## 1. Taslakta gözden geçirilen noktalar

| # | Taslak | Sorun | Revize karar |
|---|---|---|---|
| 1 | Content script API'yi "doğrudan" çağırabilir | Content script sayfanın kökeninde (https://sahibinden.com) çalışır: CORS ve karma içerik (https→http://127.0.0.1) engeli. Token da sayfaya açılmış olur. | **Yalnızca service worker** ağa çıkar. Token content script'e hiç gitmez; `chrome.storage.local`'dadır. |
| 2 | CORS `chrome-extension://*` | CORS'ta joker kök yok; ayrıca service worker `host_permissions` ile zaten CORS'a takılmaz. Gereksiz kapı. | **CORS kapalı.** Yetki = Bearer token + `Host` denetimi (DNS rebinding savunması). |
| 3 | Yetki tanımı yok | Yerel sunucuya her web sayfası istek atabilir. | `/api/v1` ayrı **EXTENSION_TOKEN** ister (panel token'ından ayrı, tek başına iptal edilebilir), boşsa API kapalı. |
| 4 | `ListingDetail`'i olduğu gibi POST | İstemci verisi güvensizdir: `raw_html_path`, `fetched_at` gibi sunucu alanları, sınırsız metin, sahte parça adları. | Ayrı **`AnalyzeRequest`** şeması: sınırlar, beyaz liste, sunucu zaman damgası, metinde telefon maskeleme (kural 5, çift katman: istemci + sunucu). |
| 5 | `batch-evaluate` yalnızca okur | Piyasa verisi DB'de yoksa (soğuk başlangıç) hiçbir şey hesaplanamaz. | Sayfada **zaten görünen** satırlar yerel piyasa DB'sine **pasif olarak eklenir** (`remember`). Ek istek yok; toplama kuralları (düşük hacim) etkilenmez. |
| 6 | Rozet: "Kelepir" / "Pahalı" | Fiyat tek başına karar değildir; %20+ ucuz ilan çoğu kez dolandırıcılık/gizli hasardır (proje kuralı). Liste rozeti 🟢/🔴 karnesini taklit etmemeli. | Rozetler **yalnız fiyata dair** ve nötr: *Fiyat avantajlı*, *Piyasada*, *Pahalı*, **⚠ Çok ucuz: önce nedenini sor**, *Emsal yetersiz*. Etiket tahmini yok. |
| 7 | Tuzak kelimeler istemcide vurgulanır | Bağlamsız ("tramer yok" da kırmızı olur), kanıtsız. | **Yalnız sunucunun doğruladığı alıntılar** vurgulanır (LLM bulgusu + kanıt kuralı). Yerel kelime listesi yok. |
| 8 | "WhatsApp teklif metni" | Metne **üst sınır** girerse pazarlık biter; LLM'den gelen metin satıcıya gidecek riskli içerik olur. | Metin deterministik şablondur: yalnız **açılış teklifi** + ilanda yapısal olarak görünen kusurlar + "ekspertiz şartıyla". Üst sınır yalnız kullanıcıya gösterilir. Eklenti metni **kopyalar, göndermez**. |
| 9 | `*vasita*` eşleşmesi | Sahibinden arama adresleri `/otomobil`, `/arazi-suv-pickup` gibi görünür; `vasita` geçmeyebilir (DOĞRULANMADI). | Arama betiği tüm sahibinden sayfalarında (ilan hariç) çalışır, **satır imzası yoksa hemen çıkar**. Kesin eşleşme gerçek sayfalarla doğrulanacak. |
| 10 | `activeTab`, `notifications` izinleri | Kullanılmıyor; fazla izin. | Yalnız `sidePanel`, `storage`. Özel sunucu adresi için izin çalışma anında, tek bir kök için istenir (`optional_host_permissions`). |
| 11 | Durum bellekte tutulur | MV3 service worker her an öldürülür. | Durum `chrome.storage.session` (sekme kimliğiyle); side panel `storage.onChanged` ile canlı güncellenir. |
| 12 | Her ilan açılışında LLM | Maliyet ve kota. | Açıklama özeti (hash) önbelleği (mevcut), günlük üst sınır (`ANALYZE_DAILY_LIMIT`), kapatılabilir otomatik analiz. LLM yoksa **"analiz bekliyor"**; asla "temiz". |
| 13 | DOM seçicileri varsayımsal | Proje kuralı: seçiciler gerçek sayfadan çıkarılır. | Seçiciler **tek dosyada** (`lib/selectors.js`), `UNVERIFIED` işaretli; okunamazsa eklenti **bilinmeyeni "iyi" saymaz**: "sayfa okunamadı" der. Yan panelde **"Sayfa yapısını indir (maskeli)"** düğmesi, gerçek fixture üretmeyi kolaylaştırır. |
| 14 | Highlight için `innerHTML` riski | Satıcı metni güvensiz; XSS. | Yalnız `createElement/textContent`; metin düğümleri bölünür. Yeniden çalıştırma güvenli (önce eski işaretler kaldırılır). |

## 2. Değişmez kurallar (eklentiye uygulanmış hâli)

1. **Eklenti sahibinden'e hiçbir istek atmaz.** Yalnızca kullanıcının zaten açtığı sayfayı okur. Arka planda ilan açmak, sayfalamak, "zenginleştirmek" yoktur (test denetler).
2. Doğrulama/CAPTCHA sayfasında eklenti **hiçbir şey yapmaz**; aşmaya çalışmaz, parmak izi/proxy yoktur.
3. Satıcı adı ve telefonu okunmaz, gönderilmez, saklanmaz (telefon desenleri her iki uçta maskelenir).
4. Karar mantığı yalnızca sunucudadır; eklenti etiket üretmez, yalnız gösterir. 🟢 = "ekspertize götürmeye değer".
5. Bilinmeyen veri "iyi" sayılmaz: eksik alan → "okunamadı", LLM yok → "analiz bekliyor".

## 3. Veri akışı

```
sahibinden sayfası ──(DOM okuma)──► content script ──runtime.sendMessage──► service worker ──fetch(Bearer)──► /api/v1
                                         ▲ vurgu/rozet                              │ chrome.storage.session
                                         └──────────────── yanıt ◄──────────────────┤
                                                        side panel ◄── onChanged ───┘
```

## 4. Uç noktalar (`/api/v1`, `EXTENSION_TOKEN` zorunlu)

| Uç nokta | Amaç |
|---|---|
| `GET /ping` | Bağlantı/yetki testi (ayarlar sayfası) |
| `POST /analyze` | Tek ilan: LLM röntgeni + piyasa + kural motoru + teklif. Karne, kanıt alıntıları, WhatsApp metni |
| `POST /batch-evaluate` | Arama sayfası: LLM'siz hızlı fiyat rozeti + (isteğe bağlı) pasif piyasa kaydı |

## 5. Bilinen sınırlar (dürüstlük)

- DOM seçicileri gerçek sahibinden HTML'iyle **doğrulanmadı**; eklenti testleri sentetik fixture ile koşar.
- `chrome.sidePanel.open` yalnızca kullanıcı hareketiyle çalışır; rozete tıklayarak açma gerçek Chrome'da denenmedi.
- Çok kullanıcılı/herkese açık sunucu (galericilere dağıtım) ayrı bir ürün kararıdır: hesap sistemi, kota, KVKK ve
  sahibinden kullanım şartları gerektirir. Bu sürüm **tek kullanıcı, yerel/Tailscale** içindir.
- Piyasa medyanı yalnızca kullanıcının gezdiği/topladığı ilanlardan oluşur; gezdikçe iyileşir. n<5 iken fiyat rozeti "emsal yetersiz" der.
