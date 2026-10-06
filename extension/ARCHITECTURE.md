# otoXray AI — Mimari ve Karar Kayıtları

otoXray AI, kullanıcının **kendi tarayıcısında zaten açtığı** araç ilanı sayfasındaki teknik veriyi okuyup yerel bir
API'ye çözümletir ve sonucu sayfanın yanında gösterir. Bir bot/crawler değildir: siteye kendi başına istek atmaz.

## 1. Pazarlıksız kurallar ve kodda nasıl karşılandıkları

| Kural | Uygulama | Doğrulayan test |
|---|---|---|
| Merkezi kazıma/botlama yok | Sunucu uygulaması (`xray_app`) toplayıcı, zamanlayıcı, ayrıştırıcı, DB kodlarını **içe aktarmaz**. Eklenti siteye hiç istek atmaz; yalnız açık sayfayı okur. | `test_api_app_imports_no_scraper_database_or_panel_code`, `test_extension_never_requests_the_site_by_itself` |
| Kişisel veri (KVKK) yok | Satıcı alanları için seçici tanımlı değil; ad/telefon/profil okunmaz. Açıklamadaki telefon numaraları **iki uçta** maskelenir. İstek şemasında bağlantı (URL), konum, satıcı türü alanı yok. | `test_phone_numbers_masked_before_reaching_the_llm`, `test_url_and_personal_fields_are_ignored_not_processed`, e2e KVKK testi |
| Durumsuz API | Veritabanı, dosya, önbellek, günlük yok (`access_log=False`). Günlük LLM sınırı yalnız zaman damgası sayar. | `test_nothing_is_written_to_disk_or_db` |
| Marka ihlali yok | Ürün adı **otoXray AI**. Site adı yalnızca manifest eşleşmesinde ve tek sabit dosyada (`lib/site.js`) alan adı olarak geçer (teknik zorunluluk); arayüz, ad, simge, metin ve kodun geri kalanında yok. | `test_no_brand_name_in_product_code` |
| Yasal uyarı | Yan panel altbilgisi, ayarlar, arama çubuğu ve **API'nin döndürdüğü her rapor** (`yasal_uyari`). Tek kaynak: `report/legal.py` ↔ `lib/legal.js`. | `test_disclaimer_text_is_exact`, `test_disclaimer_in_every_report`, e2e |
| Engel aşma yok | CAPTCHA/parmak izi/proxy kodu yok; tarayıcı otomasyonu yok. | (kod incelemesi) |

## 2. Veri akışı

```
ilan sayfası ──(DOM okuma)──► içerik betiği ──runtime.sendMessage──► service worker ──fetch(Bearer)──► /api/v1 (durumsuz)
                                    ▲ vurgu/rozet                          │  chrome.storage.local : emsal deposu, 12 sa sonuç önbelleği
                                    └───────────── yanıt ◄─────────────────┤  chrome.storage.session: sekme sonucu
                                                       yan panel ◄── onChanged ┘
```

## 3. Önemli tasarım kararları

1. **Piyasa kullanıcının tarayıcısında.** Emsal fiyatlar (yalnız yıl, km, fiyat; başlık/bağlantı yok) yerel depoda birikir
   ve her istekte *geçici* gönderilir; sunucu hesaplayıp unutur. Böylece sunucuda ilan veri tabanı oluşmaz.
2. **Yalnız service worker ağa çıkar.** İçerik betiği sayfa kökeninde çalışır (CORS/karma içerik sorunu, token sızıntısı).
3. **CORS yok.** Service worker `host_permissions` ile CORS'a takılmaz; yetki = Bearer `EXTENSION_TOKEN` + `Host` beyaz listesi
   (DNS rebinding savunması). Özel sunucu adresi için izin çalışma anında, yalnız o kök için istenir.
4. **Sonuç vurgusu yalnız sunucunun doğruladığı alıntılarla.** Yerel "tuzak kelime" listesi yok (bağlamsız: "tramer yok" da kırmızı olurdu).
5. **Liste rozetleri yalnız fiyata dair ve nötr** ("Fiyat avantajlı", "Piyasada", "Pahalı", "⚠ %20+ ucuz: önce nedenini sor",
   "Emsal yetersiz"). "Kelepir" yok; etiket tahmini yok. Emsal n<5 ise rozet "emsal yetersiz" der.
6. **Teklif metni deterministik şablon**; üst sınır metne girmez; eklenti yalnız **kopyalar**, göndermez.
7. **Bilinmeyen "iyi" sayılmaz:** okunamayan zorunlu alan → "sayfa okunamadı", LLM yok → "analiz bekliyor"; ikisinde de karar/etiket üretilmez.
8. **Yerel veri silinebilir** (ayarlar → "Yerel verileri sil"); emsaller 30 gün, sonuçlar 12 saat sonra kendiliğinden düşer.

## 4. Uç noktalar (`/api/v1`, `EXTENSION_TOKEN` zorunlu, durumsuz)

| Uç nokta | Amaç |
|---|---|
| `GET /ping` | Bağlantı/yetki testi |
| `POST /analyze` | Tek ilan: LLM açıklama röntgeni + piyasa + kural motoru + teklif. Yanıt: karne, kanıt alıntıları, vurgu listesi, WhatsApp metni, `yasal_uyari` |
| `POST /batch-evaluate` | Arama sayfası: LLM'siz fiyat rozetleri (istekle gelen emsalle) |

## 5. Bilinen sınırlar ve açık riskler (dürüstlük)

- **Hukuki risk "sıfır" olarak garanti edilemez.** Bu belge teknik önlemleri kaydeder; hukuki değerlendirme değildir. İlan sitesinin
  kullanım şartları, istemci tarafı okumayı da kısıtlayabilir; KVKK aydınlatma/açık rıza ve LLM sağlayıcısına aktarım,
  ticari dağıtım öncesi **avukat incelemesi** gerektirir.
- **LLM sağlayıcısı üçüncü taraftır:** açıklama metni (telefonlar maskeli) yapılandırılan LLM havuzuna gider; sunucu saklamasa da bu bir aktarımdır.
- DOM seçicileri gerçek sayfayla **doğrulanmadı**; testler sentetik fixture ile koşar.
- `chrome.sidePanel.open` yalnız kullanıcı hareketiyle çalışır; rozetten panel açma gerçek Chrome'da elle denenmedi.
- Çok kullanıcılı/herkese açık sunucu ayrı bir üründür (hesap, kota, KVKK, şartlar). Bu sürüm tek kullanıcı, yerel/Tailscale içindir.
- Kişisel kullanım aracındaki (`arac search/watch`) toplayıcı bu ürünün **parçası değildir** ve dağıtılmamalıdır.
