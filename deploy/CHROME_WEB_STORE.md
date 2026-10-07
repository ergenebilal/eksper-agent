# Chrome Web Store yayını (Liste dışı)

Amaç: davet e-postasındaki tek tık "Chrome'a ekle". Görünürlük **Liste dışı** (aramada çıkmaz, yalnız bağlantıyla).
Paket: `uv run python scripts/magaza_paketi.py` → `dist/cyberoto-eklenti-<sürüm>.zip` (mağaza sürümünde tek izin: canlı sunucu).
Görseller: `uv run python scripts/magaza_gorselleri.py` → `design/magaza/`.

## 1. Yeni öğe
Geliştirici panosu → **Yeni öğe** → `dist/cyberoto-eklenti-0.2.0.zip` yükle.

## 2. Mağaza girişi (Store listing)
- **Açıklama** (aşağıdaki metin), **Kategori:** Alışveriş, **Dil:** Türkçe
- **Mağaza simgesi (128×128):** `extension/icons/icon-128.png`
- **Ekran görüntüleri (1280×800):** `design/magaza/ekran-1-karne.png` … `ekran-5-belge.png`
- **Küçük tanıtım kutusu (440×280):** `design/magaza/tanitim-kutusu-440x280.png`
- **Ana sayfa URL'si:** `https://cyberoto.cybergene.co` · **Destek URL'si:** `https://cyberoto.cybergene.co/kurulum`

Açıklama:
```
CyberOto AI, araç ilanlarını ekspertize gitmeden önce okuyan bir yan panel eklentisidir.

Açtığınız ilanda:
• Karne: Alınır / Düşünülebilir / Alınmaz ve güven puanı. 🟢 “ekspertize götürmeye değer” demektir, “satın al” değil.
• Kanıtlı bulgular: açıklamadaki kusurlar ve belirsiz ifadeler, ilandan birebir alıntıyla.
• Piyasa kıyası: gezdiğiniz arama sayfalarındaki benzer ilanlarla.
• Tahmini gerçek maliyet ve açılış teklifi.
• Aday karşılaştırma: 2-5 ilan yan yana, ekspertize gitme sırasıyla.
• Belge röntgeni: ekspertiz raporunu ya da hasar kaydını ilanla karşılaştırır.

Kapalı beta: yalnızca davet edilen e-posta adresleriyle kullanılabilir.

Eklenti yalnızca sizin açtığınız sayfaları okur; arka planda sayfa taramaz. İlan metni analiz için sunucuya gider ve saklanmaz.

Bu yazılım bir yapay zeka metin analizi ve karar destek aracıdır. Resmi ekspertiz raporu niteliği taşımaz.
```

## 3. Gizlilik uygulamaları (Privacy practices)
**Tek amaç:**
```
Kullanıcının tarayıcıda açtığı ikinci el araç ilanını yan panelde değerlendirmek: açıklamadaki kusurları alıntıyla göstermek, fiyatı benzer ilanlarla kıyaslamak ve ilanın ekspertize götürülmeye değip değmediğini söylemek.
```
**İzin gerekçeleri:**
- `sidePanel`: `Analiz sonucu tarayıcının yan panelinde gösterilir.`
- `storage`: `Giriş anahtarı, ayarlar, kullanıcının gezdiği arama sayfalarındaki emsal fiyatlar ve aday havuzu yalnız kullanıcının tarayıcısında saklanır.`
- Ana makine izni: `İlan sitesinin ilan ve arama sayfalarını yalnızca kullanıcı açtığında okumak ve analiz için kendi sunucumuz cyberoto.cybergene.co ile iletişim kurmak. Eklenti siteye kendi başına istek göndermez, arka planda sayfa taramaz.`
- İsteğe bağlı ana makine izinleri (sorulursa): `Yalnızca kullanıcı Gelişmiş ayarlarda kendi sunucu adresini girerse o adres için izin istenir; varsayılan kullanımda istenmez.`

**Uzak kod:** Hayır, uzak kod kullanmıyorum.

**Veri kullanımı** — işaretlenecekler: *Kişisel olarak tanımlayıcı bilgiler* (e-posta adresi, giriş için),
*Kimlik doğrulama bilgileri* (cihaz anahtarı), *Web sitesi içeriği* (açılan ilanın metni, analiz için; saklanmaz).
Diğerleri işaretlenmez. Üç beyan kutusunun üçü de işaretlenir (satılmaz, amaç dışı kullanılmaz, kredi değerlendirmesinde kullanılmaz).

**Gizlilik politikası URL'si:** `https://cyberoto.cybergene.co/gizlilik`

## 4. Dağıtım
**Görünürlük:** Liste dışı · **Bölgeler:** Türkiye (ya da tümü) · Ücretsiz.

## 5. İncelemeye gönder
Onay genelde 1-3 iş günü (bazen daha uzun). Onaylanınca öğe sayfasının bağlantısı (`https://chromewebstore.google.com/detail/...`)
sunucu `.env` dosyasına `STORE_URL=` olarak girilir ve servis yeniden başlatılır: davet e-postasındaki düğme "Chrome'a ekle" olur,
kurulum sayfası tek adıma iner.

Sürüm güncellemesi: `extension/manifest.json` sürümünü artır → `scripts/magaza_paketi.py` → panoda "Paket" sekmesinden yeni zip.
