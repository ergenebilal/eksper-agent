# CyberOto AI — Chrome Eklentisi (Manifest V3)

Araç ilanı sayfasını açtığınızda ilan açıklamasını yapay zekayla tarar, piyasa kıyası ve teklif önerisi çıkarır.
**Yapay zeka karar destek aracıdır; resmi ekspertiz raporu değildir.** Mimari ve kurallar: [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Sunucuyu başlat (durumsuz API)

`.env` dosyasına (en az 16 rastgele karakter) ve LLM havuzu bilgilerine ekleyin:

```
EXTENSION_TOKEN=<uzun-rastgele-bir-değer>
LLM_BASE_URL=...  LLM_API_KEY=...  LLM_MODEL_FAST=...  LLM_MODEL_STRONG=...
```

```bash
uv run arac xray serve        # http://127.0.0.1:8991 — token yoksa BAŞLAMAZ
```

Sunucu hiçbir şey saklamaz (DB/dosya/önbellek/erişim günlüğü yok). Telefondan/başka makineden kullanacaksanız
`XRAY_HOST` ve `PANEL_ALLOWED_HOSTS` ayarlayın; **internete açmayın** (yalnız yerel ağ/Tailscale).

## 2. Eklentiyi Chrome'a yükle (Geliştirici Modu)

1. `chrome://extensions` → sağ üstten **Geliştirici modu**'nu aç.
2. **Paketlenmemiş öğe yükle** → bu deponun `extension/` klasörünü seç.
3. İlk kurulumda **Ayarlar** açılır: sunucu adresi (`http://127.0.0.1:8991`) ve `EXTENSION_TOKEN` değerini girip
   **Kaydet** → **Bağlantıyı test et** (“✓ Bağlantı ve anahtar doğru”).
4. Desteklenen ilan sitesinde bir ilan açın: açıklamada vurgular + sağ altta rozet çıkar; eklenti simgesine tıklayınca
   yan panelde karne açılır. Arama sonuçları sayfasında fiyat rozetleri ve “🚀 Bu sayfayı eksperle” düğmesi çıkar.

Kod değişince `chrome://extensions` üzerinden eklentiyi yenileyin (↻). Service worker günlüğü: **Service worker → İncele**.

## 3. Nasıl çalışır (özet)

- **Detay sayfası:** fiyat, km, yıl, hasar tablosu ve açıklama okunur (telefonlar maskelenir) → service worker → `/analyze`.
  Sunucunun açıklamada **doğruladığı** alıntılar işaretlenir: kırmızı = olumsuz, sarı = belirsiz, yeşil = olumlu (satıcı beyanı).
- **Arama sayfası:** satırlardaki fiyat/yıl/km ile **yalnız fiyat** kıyası (`/batch-evaluate`); karar değildir.
  Sayfada gördüğünüz satırlar tarayıcınızda **yerel emsal** olarak birikir; aynı modeli gezdikçe kıyas iyileşir.
- **Teklif metni:** yan panelden kopyalanır; göndermeyi siz yaparsınız. Üst sınır metne girmez.

## 3b. Hız

Analizin süresi neredeyse tamamen LLM havuzunun gecikmesidir (ölçüm: içeriksiz tek satırlık çağrı bile ~9-15 sn; her
tam geçiş ~15-25 sn). Bu yüzden:
- **Ön hesap** (`/quick`, LLM'siz, <1 sn): piyasa ortalaması, yapıdan elenme nedenleri (bütçe, tavan, yıllık km…) ve ön teklif,
  LLM röntgeni beklenirken yan panelde hemen görünür; bekleme sayacı çalışır.
- **İkinci geçiş** varsayılan olarak yalnız 🔴 nedeni olabilecek iddialarda (şase/airbag/motor/pert) çalışır
  (`XRAY_SECOND_PASS=hard`); `off` ile tamamen kapatılabilir, `all` eski davranıştır.
- Aynı ilan 12 saat boyunca tarayıcıda önbelleklenir (ikinci açılış anında).

## 4. Test

```bash
uv run pytest tests/test_xray_api.py           # API: yetki, durumsuzluk, KVKK, uyarı metni (hızlı)
uv run pytest tests/test_extension_e2e.py      # gerçek Chromium + eklenti + sentetik sayfalar (≈10 sn)
uv run pytest                                  # tüm paket
```

Uçtan uca test eklentiyi gerçek Chromium'a yükler, ilan sayfalarını **ağ yerine yerel fixture ile** sunar ve siteye hiçbir
istek gitmediğini denetler. Chromium yoksa: `uv run playwright install chromium`.

## 5. Sayfa düzeni değişirse / gerçek sayfayla doğrulama

Okuma kuralları (`lib/selectors.js`) **gerçek sayfayla doğrulanmadı** (UNVERIFIED). Eklenti okuyamadığı zorunlu alanı tahmin
etmez; yan panel “Sayfa okunamadı” der. Düzeltmek için: sayfayı tarayıcıdan **Farklı kaydet → Web Sayfası, Yalnızca HTML**
ile kaydedin, **satıcı adı/telefonu içeren kısımları silin**, `extension/tests/fixtures/` altına koyun ve yalnızca o dosyadan
`selectors.js` değerlerini güncelleyin; ardından e2e testini yeni fixture'a uyarlayın.

## 6. Gizlilik ve sınırlar

- Satıcı adı, telefonu, profili **okunmaz/gönderilmez/saklanmaz**. İstekte bağlantı (URL) ve konum da yoktur.
- Açıklama metni (telefonlar maskeli) yapay zeka analizi için **yapılandırdığınız LLM sağlayıcısına** gider.
- Emsal fiyatlar ve sonuç önbelleği yalnız bu tarayıcıda durur; ayarlardan **Yerel verileri sil** ile silinir.
- Hukuki risk teknik önlemlerle “sıfırlanamaz”; ticari dağıtım öncesi avukat görüşü alın (ARCHITECTURE.md §5).
