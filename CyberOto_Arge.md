# CyberOto — Ar-Ge Planı ve Takip Dosyası

> **Bu dosya canlı takip dosyasıdır.** İşi devralan her ajan (Claude, Codex, başka bir model) önce bu dosyayı,
> sonra `CLAUDE.md`'yi okur. İş paketini başlatırken durumunu `🔄`, bitirince `✅` yapar ve en alttaki
> **İlerleme günlüğü**ne bir satır ekler. Kararı kullanıcıya ait konular **Açık kararlar** bölümündedir: tahmin edilmez, sorulur.

Son güncelleme: 2026-10-07 (R0–R5 yazılım işleri tamam) · Hazırlayan: Claude (oturum 5d82b169)

---

## 0. Devralan ajan için 5 dakikalık başlangıç

1. `git status`, `git log --oneline -5`. Çalışma dalı: **`feat/f0-eval`** (main'e göre ~50 commit önde, **push edilmedi**, push kullanıcıya ait).
2. Testler: `uv run pytest -q` (≈4,5 dk, 457 test; `tests/test_extension_e2e.py` gerçek Chromium ister: `uv run playwright install chromium`).
3. Canlı sistem: `https://cyberoto.cybergene.co` (sağlık: `/healthz`; eski `otoxray.cybergene.co` yalnız API'yi sunar, tarayıcıyı yönlendirir). Yayın: `bash deploy/redeploy.sh` (yalnız **commit edilmiş** kodu gönderir).
4. Ayrıntılı altyapı: [deploy/README.md](deploy/README.md) · ürün kararları: [PLAN.md](PLAN.md) · tasarım tokenları: [design/cybergene-dna.json](design/cybergene-dna.json).
5. Bir sonraki iş: R0–R5 yazılım işleri bitti (2026-10-07). Kalanlar **kullanıcı girdisi** bekliyor → **§7 Açık kararlar**. Girdi gelince ilgili pakete dön.
6. Ürün adı **CyberOto AI** (eski: otoXray). Alan adı `cyberoto.cybergene.co` (P.7). İç teknik adlar bilerek değişmedi: systemd `otoxray`, `/opt/otoxray`, anahtar öneki `oxr_`.

## 1. Ürün ve mevcut durum (6 Ekim 2026)

**CyberOto AI** — CyberGene ürünü. Kullanıcının kendi tarayıcısında açtığı araç ilanını okuyan Chrome eklentisi + sunucu.
🟢 = "ekspertize götürmeye değer", **"satın al" değil**. Kapalı B2C beta: davetli kullanıcılar, kişiye özel haklar.

| Bileşen | Durum | Yer |
|---|---|---|
| Eklenti (MV3): ilan sayfası okuma, yan panel karnesi, arama sayfası fiyat rozetleri | ✅ seçiciler 18 gerçek ilan + 3 arama sayfasıyla doğrulandı (R0) | `extension/` |
| Aday Karşılaştırma (havuz + karşılaştır), sinyaller, belge röntgeni, kalibrasyon | ✅ R3–R5 | `analysis/compare.py`, `sinyaller.py`, `likidite.py`, `belge.py` |
| Ücretsiz ön hesap (LLM'siz: piyasa, yapısal elenme, ön teklif) — ilan açılınca | ✅ | `api.py:/quick` |
| Yapay zeka röntgeni (açıklama analizi, kanıt alıntılı) — yalnız düğmeyle, 1 hak | ✅ | `api.py:/analyze`, `analysis/description_llm.py` |
| Aynı ilan + aynı açıklama 7 gün ücretsiz tekrar (yalnız hash) | ✅ | `accounts.py: charges` |
| E-postaya bağlı üyelik, kodla giriş, günlük/aylık hak, bitiş, rozet izni | ✅ | `web/accounts.py`, `api.py:auth_router` |
| Yönetim sayfası `/yonetim` (üyeler, davetler, geri bildirim) | ✅ | `web/yonetim.py`, `templates/yonetim/` |
| CyberGene HTML e-postaları (davet, kod) — Spaceship SMTP | ✅ canlıda doğrulandı | `web/mailer.py`, `templates/email/` |
| Ölçüm altyapısı: 50 etiketli açıklama, `arac eval` (recall ≥ %90 kapısı) | ✅ (sentetik vakalar) | `analysis/evaluation.py`, `tests/data/` |
| Kişisel araç: Playwright toplayıcı + Radar (Telegram) | ✅ ama **ürünün parçası değil**, dağıtılmaz | `collector/`, `watcher/` |

Canlı: Hermes sunucusu (`hermes@100.80.122.74`, genel IP 13.140.183.88), `/opt/otoxray`, systemd `otoxray`, nginx site `otoxray.cybergene.co`.

## 2. Değiştirilemez kurallar (her pakette geçerli)

1. **Siteye kendi başına istek yok.** Eklenti yalnızca kullanıcının açtığı sayfayı okur. Arka planda ilan çekme, takip, tarama **yasak**. Sunucu toplayıcı kodu içe aktarmaz (testle denetlenir).
2. **Satıcı kişisel verisi okunmaz/saklanmaz** (ad, telefon, profil, diğer ilanları). Açıklamadaki telefonlar iki uçta maskelenir.
3. **Sunucu ilan içeriği saklamaz.** İzin verilen kalıcı kayıtlar: üye hesabı, sayaçlar, hash'ler, kullanıcının bilerek gönderdiği geri bildirim. İlan metni gereken her şey kullanıcının tarayıcısında (`chrome.storage.local`) tutulur.
4. **LLM çıktısı kanıtsız kabul edilmez.** Her bulgu açıklamadan birebir alıntı taşır; alıntı metinde yoksa bulgu düşer. Model iç alanları (ör. `dogrulanamayan_iddia`) kendisi dolduramaz.
5. **LLM sayı uydurmaz.** TL tutarları, süreler, oranlar ya **ilan metninden alıntı** ya **yapılandırılmış bilgi tabanından** (YAML) gelir; LLM yalnızca kalemi tanır ve eşler. Tahminler **aralık** olarak ve "tahmini" etiketiyle gösterilir.
6. **Bilinmeyen "iyi" sayılmaz.** Eksik veri nötr değil, hafif negatif / "sorulmalı" maddesidir.
7. **İtham dili yok.** Kişiler hakkında hüküm verilmez ("gizli alsatçı", "dolandırıcı" denmez); "sinyal" + alıntı gösterilir, karar kullanıcıya bırakılır.
8. **Hak ekonomisi şeffaf.** Hak yalnızca açık bir kullanıcı eylemiyle düşer; düğmede ne kadar hak kullanacağı yazar; başarısız işlem iade edilir.
9. **Her değişiklik testle gelir.** LLM davranışını etkileyen değişiklik (prompt, sözlük, şema) `arac eval` öncesi/sonrası ölçümüyle gelir.
10. **Bilgi tabanları insan onaylıdır.** `models_kb.yaml`, `masraf_kb.yaml`, `jargon.yaml`: LLM taslak üretebilir, **kullanıcı onaylamadan canlıya girmez**. Her kayıtta kaynak/tarih.

## 3. Fikirlerin değerlendirmesi (Claude'un bakışı)

Kullanıcının önerileri (1: Aday Karşılaştırma, 2A–2E) aşağıda **değer / risk / bizim kısıtlarımızla uyum** açısından değerlendirildi.
Özet: hepsi doğru yönde. En yüksek değer/maliyet oranı **E (araca özel ekspertiz)**, **C (soru çarşafı)** ve **B (gerçek maliyet)**;
**Aday Karşılaştırma** ürünü "tek ilan aracı"ndan "karar aracı"na çeviren ana özellik. **D (likidite)** ve **gizli alsatçı** veri eksikliği nedeniyle
dürüst sınırlarla, düşük güvenle başlamalı.

### 1 · Aday Karşılaştırma (Havuz + Karşılaştır ve Karar Ver) — ⭐ ana özellik
- **Neden güçlü:** Gerçek alıcı tek ilana değil, 3-5 aday arasında karar verir. Bugün CyberOto her ilanı tek başına puanlıyor; karşılaştırma eksik.
- **Kısıtlarla uyum:** Havuz **kullanıcının tarayıcısında** tutulur (ilan verisi sunucuda saklanmaz). Karşılaştırma isteğinde seçili ilanların verisi geçici gönderilir, sunucu hesaplayıp unutur.
- **Zenginleştirme:**
  - Karşılaştırmanın **sayısal iskeleti deterministik** olsun: fiyat, piyasa sapması, km/yıl, puan, tramer, gerçek maliyet (B), likidite (D) — tablo halinde. LLM yalnızca bu tablodan **gerekçeli sıralama ve anlatı** üretir; tabloda olmayan bir sayı söyleyemez (çıktı doğrulanır).
  - Üç sonuç: **Fiyat/performans galibi**, **en riskli**, **pazarlık şansı en yüksek** + "ekspertize önce şunu götür" sırası.
  - **Ön koşul:** karşılaştırılan her ilanın röntgeni yapılmış olmalı (yoksa panel "önce röntgen" der; aynı ilan tekrar ücretsiz olduğu için adil).
  - **Hak:** karşılaştırma = 1 hak (ilan sayısından bağımsız). Aynı küme tekrar ücretsiz (hash).
  - **"45 gündür ilanda":** eklentinin ilan tarihini okuması gerekir (bugün okumuyor → seçici eklenecek, gerçek sayfayla doğrulanacak). **Fiyat düşüş geçmişi** yalnızca kullanıcının **kendi ziyaretlerinden** oluşur (her açılışta havuzdaki ilanın fiyatı anlık kaydedilir). Bunu açıkça "sizin gördüğünüz fiyatlar" diye yazmalıyız; tam geçmiş iddia edilmez.
  - Havuzdaki ilan satıldıysa/kalktıysa bunu ancak kullanıcı tekrar açınca anlarız (arka planda kontrol yok — kural 1).

### 2A · Satıcı psikolojisi ve fırsat radarı
- **Aciliyet dedektifi:** Değerli ve kolay: kalıplar ("ev alacağım için", "acil", "bugünlük", "takas yok nakit") LLM'in zaten çıkardığı sinyallere yeni bir kategori olarak eklenir, **alıntı zorunlu**.
  - **Değişiklik önerisi:** 0-100 skor yerine **3 bant** (düşük / orta / yüksek) + alıntılar. 0-100, elimizdeki veriyle olmayan bir hassasiyet ima eder.
  - Fiyat düşüşü sinyali yalnızca kullanıcının kendi gözlemlerinden (Aday Karşılaştırma snapshot'ları).
  - Pazarlık marjına bağlanır: yüksek aciliyet → teklif aralığı biraz aşağı (kural tabanlı, `rules.yaml`).
- **Gizli alsatçı filtresi:** Dikkatli olunmalı.
  - Fotoğraf çekim tarzı → görsel analiz gerektirir (Faz 4'e). Satıcının diğer ilanları → **okunmaz** (kural 2).
  - Yapılabilir olan: **metindeki ticari dil sinyalleri** ("galerimizde", "kredi/senet imkanı", "takas kabul edilir", toplu ilan şablonu dili) → "**Ticari satıcı sinyali**" (itham değil, kural 7) + alıntı + "sahibinden etiketli ama ticari dil kullanıyor, sorun" önerisi.
  - Neden önemli: ticari satıcıda ayıplı mal sorumluluğu ve fatura farkı olur → **soru çarşafına** madde düşer.

### 2B · Gerçek maliyet hesaplayıcı — ⭐ yüksek değer
- **Doğru fikir; kritik risk: LLM'in TL uydurması.** Bu yüzden iki katmanlı:
  1. LLM metinden masraf kalemlerini **alıntıyla** çıkarır ("klimaya gaz basılacak" → `klima_gaz`).
  2. Tutar **`config/masraf_kb.yaml`**'dan gelir: kalem × segment (A/B/C/D/SUV/premium) için **min-max aralık**, tarih ve kaynak. KB'de olmayan kalem "tutar bilinmiyor, usta fiyatı alın" olur.
- **Zenginleştirme:**
  - **Km tetikli bakım maliyeti** (metinde geçmese de): `models_kb` bakım aralıkları + araç km'si (ör. triger 90-120 bin km'de, ilanda "triger yapıldı" yoksa → beklenen masraf, "yapıldı mı sorun").
  - **Muayene** yakınsa (sayfada muayene tarihi alanı varsa) masraf değil ama soru maddesi.
  - Sonuç: "İlan 800.000 TL → **tahmini gerçek maliyet 820-845.000 TL**" (aralık) + kalem dökümü.
  - **Teklife bağlanır:** `offer.py` gerçek maliyetin alt sınırını açılış teklifinden düşer; dayanakta kalem kalem gösterilir.
  - Karşılaştırmada (1) kullanılan sayı "ilan fiyatı" değil "tahmini gerçek maliyet"tir.

### 2C · Pazarlık koçu ve telefon senaryosu — ⭐ hızlı kazanım
- **Neredeyse tamamen mevcut veriden üretilebilir:** `UNKNOWN` parçalar, tramer bilinmiyor, belirsiz ifadeler, kronik arıza, km tetikli bakım, ticari dil sinyali, aciliyet. Her biri bir **soru**ya dönüşür.
- **Zenginleştirme:**
  - Sorular **öncelik sırasıyla** (önce eleyici: tavan/şase/airbag/tramer; sonra maliyetli: triger/şanzıman; sonra pazarlık).
  - Her soru için "**cevap şuysa → ne anlama gelir**" (ör. "tramer 40 binin üstüyse ekspertize gitmeden fiyatı tekrar konuşun").
  - "Satıcıya gitmeden önce iste": tramer sorgusu ekran görüntüsü, servis kayıtları, ekspertiz izni.
  - Kopyala düğmesi (mevcut WhatsApp metni gibi), göndermeyi kullanıcı yapar.
  - Fotoğraftan gelen sorular ("direksiyon kılıfı") görsel analiz gelince (Faz 4).
  - **Hak:** röntgene dahil (ek hak yok); deterministik iskelet + kısa LLM ifadesi.

### 2D · Likidite (piyasa hızı) skoru
- **Gerçek sorun:** "Satması 15-20 gün sürer" demek için **satış süresi verisi** gerekir; bizde yok (satış fiyatı da yok, yalnız ilan fiyatı). LLM'in genel bilgisiyle gün söylemek uydurma riski taşır.
- **Dürüst sürüm (v0):** Gün yerine **3 bant** (hızlı / orta / yavaş) ve gerekçe:
  - Segment/kasa/yakıt/vites bilgi tabanı (`config/likidite_kb.yaml`, insan onaylı: ör. "C sedan dizel otomatik = hızlı", "büyük motorlu benzinli station = yavaş").
  - Kullanıcının tarayıcısındaki **emsal yoğunluğu** (aynı seride kaç ilan gördü) ve emsallerin **ilan yaşı** (arama sayfasından okunabilirse).
  - "Pazarlığı buna göre yapın" notu teklif dayanağına girer.
- **v1:** Geri bildirimden ("aldım/sattım, kaç günde") gerçek veri birikince kalibre edilir.

### 2E · Noter ve ekspertiz savunması — ⭐ hızlı kazanım
- Mevcut "ekspertiz kontrol listesi" genel. **Araca özel** hale getirmek için:
  - `models_kb.yaml` (şu an **boş**): en çok bakılan 30 model için kronik arızalar + **km eşiği** (ör. DSG kavrama ~120 bin km, EDC, 1.6 dizel enjektör…). LLM taslak, **kullanıcı onayı** (kural 10).
  - Km'ye göre tetiklenen test maddeleri: "120 bin km DSG → vites geçişlerinde titreme testi".
  - Röntgen bulgularından gelen maddeler ("açıklamada 'kafa yapıldı' geçiyor → kompresyon testi isteyin").
- **"Noter" kısmı (zenginleştirme):** Alım günü kontrol listesi — ruhsat/şasi no eşleşmesi, rehin/haciz sorgusu (e-Devlet), kapora yerine **güvenli ödeme** uyarısı, noter satışında ödeme sırası. Statik, düşük maliyetli, dolandırıcılık riskini azaltır. Hukuki tavsiye değildir notuyla.

### Claude'un ek önerileri
- **F · Tramer yapıştır:** Kullanıcı kendi aldığı SBM hasar sorgusu SMS'ini/ekran metnini yapıştırır → parse edilir → ilandaki beyanla **çelişki** varsa kırmızı bayrak ("ilanda 18 bin yazıyor, kayıt 64 bin"). Veri kullanıcıdan gelir, scraping yok. Çok güçlü güven sinyali.
- **G · Görsel röntgen (Faz 4):** İlan fotoğraflarından boya tonu farkı, panel aralıkları, gösterge fotoğrafındaki km ile ilandaki km tutarlılığı, direksiyon/pedal aşınması. Yalnızca "ekspertizde bak" ipucu üretir. Maliyet ve doğruluk ölçümü (eval) şart.
- **H · Karar sonrası döngü:** "Ekspertize gittim → sonuç", "aldım/almadım" → hem kalibrasyon hem likidite verisi. Geri bildirim altyapısı var; Aday Karşılaştırma'na "durum" alanı olarak bağlanır.
- **I · Gerçek ilan doğrulaması (ÖNKOŞUL):** Yukarıdaki her şey eklentinin gerçek sayfayı doğru okumasına bağlı. Seçiciler hâlâ sentetik sayfalarla test ediliyor. **Bu, R0 paketidir ve her şeyden önce gelir.**

## 3b. Gerçek sayfa bulguları (R0, 2026-10-07 — 13 ilan)

- **Bilgi satırları:** `dl.classifiedInfoList > .classifiedInfoItem > dt/dd`; 20 etiket 13/13 sayfada aynı: İlan No, **İlan Tarihi**,
  Marka, Seri, Model, Yıl, Yakıt / Motor Tipi, Vites, Araç Durumu, KM, Kasa Tipi, Motor Gücü, Motor Hacmi, Çekiş, Renk,
  Servis Garantisi, Ağır Hasar Kayıtlı, Plaka / Uyruk, **Kimden** (`dd.fromOwner`), Takas.
- **Hasar şeması:** `.car-parts > div` → 1. sınıf parça (`front-hood`, `roof`, `rear-right-mudguard`…, 13 parça), 2. sınıf durum
  (`original-new`, `painted-new`, `localpainted-new`, `changed-new`). **Eski seçiciler bunu hiç okumuyordu → canlıda hiçbir
  gerçek ilan 🟢 alamıyordu** ("parça diyagramı yok" engeli). Düzeltildi (`extension/lib/selectors.js`, `extract-detail.js`).
  Açık soru: satıcı şemayı doldurmadığında site ne gösteriyor (hepsi "orijinal" mi, ayrı sınıf mı)? → "belirtilmemiş" örnek ilan gerekli.
- **Şanzıman türü** (EDC, DSG, Powershift, DCT, CVT…) ilanın hiçbir alanında yok → KB şanzıman maddeleri vites + model + yıl ile eşleşir (varsayım, KB başında not).
- **Fiyat geçmişi:** `#price-history-dropdown` yalnız boş şablon; veriyi site tıklamayla ayrıca çeker. `input#priceHistoryFlag` (true/false)
  fiyatın değişip değişmediğini söyler → istek atmadan okunabilir. Ayrıntılı tarihçe yalnız kullanıcı açınca, sitenin doldurduğu
  DOM'dan pasif okunabilir. **Tarihçeyi kendimiz istemek kural 1 ihlalidir.**
- **Temizleme:** satıcı kutusu, giriş menüsü, bildirimler silinir; harita koordinatları (`data-lat/lon`) satıcı konumu olabileceği için
  silinir; lastik ölçüsü (`205/55 R16`) plaka sanılıyordu, düzeltildi. Ham sayfalar `data/samples/` (git dışı).
- **Python ayrıştırıcı** (kişisel araç, `parser/`) hâlâ eski sentetik seçicilerde; ürünü etkilemez → R0.4.
- **Boş/doldurulmamış hasar şeması (2. tur, 18 ilan):** site doldurulmamış şemayı 13/13 "orijinal" + "Aracın tüm parçaları
  orijinaldır" metniyle gösterir; DOM'da gerçek "hepsi orijinal" beyanından **ayırt edilemez** ("komple boyalı" başlıklı 3 ilanla
  kanıtlandı). Çözüm anlam düzeyinde: `analysis/diagram_check.py` — şema tamamen orijinal + başlık/açıklamada olumsuzlanmamış
  boya/değişen beyanı → parçalar **bilinmiyor**, 🟢 engelli, panelde "Hasar şeması güvenilir değil" uyarısı, kontrol listesine mikron
  ölçümü. Olumsuzlamalar ("boyasız", "değişeni yok", "boya işlemi yoktur"), kaporta dışı değişimler (termostat, far, filtre) ve
  "boya koruma" sayılmaz; "boyası var ama değişeni yok" doğru okunur. Çelişkisiz "tamamı orijinal" şema da kontrol listesinde
  "satıcı beyanı, boya kalınlığı ölçtürün" maddesi alır. 4/18 gerçek ilan çelişkili çıktı (elle doğrulandı).
- **"Galeriden" klasöründeki 2 ilanın Kimden alanı "Sahibinden"**: sayfa ne diyorsa o okunur; ticari dil sinyali R4.2'de.
- **Arama sayfası:** başlıklar `thead td` (th değil) → Seri sütunu okunmuyordu; metinle aramada yol `/otomobil` olduğundan emsaller
  tek havuzda birikip **farklı modeller kıyaslanıyordu** (ör. A4/A5/A7). Düzeltildi: Marka+Seri satırdan okunur, emsal grubu
  `m:marka seri` (ilan sayfalarıyla ortak havuz). Reklam satırı (`tr.nativeAd`) atlanır, "okunamadı" sayılmaz.
- **"Bu sayfayı eksperle" çubuğu** yalnız ilk sayfada çıkıyordu (tek seferlik kurulum + eski kapsayıcıya bağlı gözlemci +
  geri/ileri önbellek). Yeniden yazıldı: shadow DOM'da CyberGene tasarımı, tek belge gözlemcisiyle "tablo göründükçe yerinde tut",
  liste değişince yeniden değerlendirme, `pageshow`/`popstate`, hata sonrası 30 sn bekleme. E2E: tablo kapsayıcısıyla değişince
  ve önbellekten dönüşte çubuk geri gelir.

## 4. Mimari ilkeler (yeni özellikler için)

- **Veri yeri:** Havuz, snapshot (görülen fiyat/tarih), karşılaştırma sonuçları → `chrome.storage.local` (kullanıcı silebilir, 30-90 gün TTL). Sunucu: yalnız hesap, sayaç, hash.
- **Yeni uç noktalar** (`/api/v1`, Bearer, durumsuz): `POST /compare` (2-5 ilan + mevcut röntgen sonuçları → karşılaştırma), `POST /tramer-parse`. Hepsi hak/kota sisteminden geçer.
- **Yeni bilgi tabanları** (`arac_eksper/config/`, insan onaylı, kaynak+tarih alanlı): `masraf_kb.yaml`, `likidite_kb.yaml`; `models_kb.yaml` genişler (km eşikleri, bakım aralıkları).
- **LLM şeması:** `DescriptionFindings`'e yeni kategoriler (`aciliyet_sinyalleri`, `ticari_dil_sinyalleri`, `masraf_kalemleri`) — hepsi `Evidence` (etiket + birebir alıntı). İç alanlar parse sonrası sıfırlanır.
- **Karşılaştırma LLM çıktısı doğrulaması:** çıktıdaki her sayı, gönderilen tablodaki bir değere eşit olmalı; değilse cümle düşer.
- **UI:** CyberGene DNA'sı (`design/cybergene-dna.json`), `frontend-design` + `design-dna` skill'leri; tek cesur öğe ilkesi; ekran görüntüsüyle kontrol.

## 5. Yol haritası ve iş paketleri

Durum: ⬜ başlanmadı · 🔄 sürüyor · ✅ bitti · ⛔ engelli (nedeni yazılır) · 👤 kullanıcı girdisi bekliyor

### R0 — Önkoşul: gerçek sayfa doğrulaması
| ID | Paket | Durum | Kabul ölçütü | Dosyalar |
|---|---|---|---|---|
| R0.1 | 15-20 gerçek ilan sayfası (farklı marka, galeri/sahibinden, diyagramlı/diyagramsız) + 3 arama sayfası | ✅ 18 detay (2 "galeriden" klasörlü, 3 "komple boyalı" boş şemalı dahil) + 3 arama sayfası | Kullanıcı "Farklı kaydet" ile **`data/samples/`** klasörüne koyar (git'e girmez, ham kalır); ajan `arac fixture sanitize data/samples/*.html` ile temizleyip `tests/fixtures/real/`'a alır | `fixture_sanitizer.py` |
| R0.2 | Eklenti seçicilerini gerçek fixture'lardan çıkar (UNVERIFIED işaretlerini kaldır) + **ilan tarihi** alanı | ✅ detay 18/18 + arama 3/3 (`tests/test_real_pages.py`, e2e gerçek arama testi) · ilan tarihi okuma → R3.2'ye taşındı | Tüm gerçek fixture'larda zorunlu alanlar %100 okunur; e2e gerçek fixture ile koşar | `extension/lib/selectors.js`, `extract-*.js`, `tests/test_extension_e2e.py` |
| R0.3 | Gerçek açıklamalardan 100+ etiketli vaka (`kaynak: gercek`) | ✅ 18 taslak etiket (`tests/data/aciklamalar_gercek_taslak.jsonl`, 3 SINIRDA) · 👤 onay + daha fazla gerçek vaka · canlı ölçüm: recall 1,0, precision 1,0, tramer 1,0, olumsuz 0,92–1,0 | `arac eval` recall ≥ %90, temiz vakada 🟢 engeli ≤ %5. Başlangıç: 13 gerçek açıklama için ajan etiket taslağı → kullanıcı onayı | `tests/data/aciklamalar.jsonl` |
| R0.4 | Python ayrıştırıcıyı (`parser/selectors.py`, `damage_parser.py`) gerçek yapıya geçir (kişisel araç) | ✅ f9c1c3b: 18/18 detay + 3/3 arama bağımsız okumayla eşleşir; okunamayan tarih bugüne düşmez; toplayıcıdaki kırık seçici referansı düzeltildi, tüm `Selectors.*` referansları testli | `tests/fixtures/real` ile alan doğruluğu %100 | `parser/` |

### R1 — Hızlı kazanımlar (mevcut veriden)
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R1.1 | `models_kb.yaml` ilk 30 model: kronik arıza + km eşiği + bakım aralığı (LLM taslak → kullanıcı onayı) | ✅ taslak · 👤 onay | 32 model / 59 madde, hepsi `onayli: false`; şema + onay kuralı testli; `arac kb kontrol` | — |
| R1.2 | **E · Araca özel ekspertiz listesi**: kronik + km tetikli + bulgudan türeyen maddeler, öncelik sıralı | ✅ | `analysis/checklist.py:ekspertiz_bolumleri`: şema (çelişki/beyan, değişen parçalar) + bulgu (şase, airbag, motor, km, tramer, belirsiz ifade, LPG) + kronik + bakım, kaynak etiketli, öncelik sıralı; panelde "Bu araçta özellikle" / "Her araçta". Kronik/bakım maddeleri R1.1 onayıyla devreye girer | R1.1 |
| R1.3 | **E+ · Alım günü / noter listesi** (statik, hukuki tavsiye değildir notu) | ✅ taslak · 👤 onay | `config/alim_gunu.yaml` (5 bölüm), `GET /api/v1/rehber`, panelde açılır bölüm; onaylanınca görünür | — |
| R1.4 | **C · Soru çarşafı**: veri boşlukları + bulgular → öncelikli sorular + "cevap şuysa" + kopyala | ✅ `checklist.soru_carsafi` (1 eleyici → 2 maliyetli → 3 pazarlık, en fazla 10, dil kılavuzu testli), panelde "Satıcıya sorulacaklar" + kopyala | Her soru bir veri boşluğuna/bulguya bağlı (izlenebilir); ek hak yok; testli şablon | R1.2 (kısmen) |

### R2 — Gerçek maliyet
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R2.1 | `masraf_kb.yaml`: ~40 yaygın kalem × segment, min-max TL, tarih, kaynak (kullanıcı onaylı) | ✅ taslak (42 kalem, 4 segment, hepsi onaysız) · 👤 onay | Şema testi; tarihi 6 aydan eski kalem uyarı verir | — |
| R2.2 | LLM şemasına `masraf_kalemleri` (Evidence) + jargon; eval'e masraf vakaları | ✅ **v0 kural tabanlı** (LLM'siz, `analysis/masraf.py`): anahtar kelime + ihtiyaç ifadesi, tamamlanmış/olumsuz atlanır, uzun ifade önce; 18 gerçek ilanda 3/3 doğru, 0 yanlış alarm. LLM ile genişletme (eşanlamlılar) → R2.2b ⬜ | Masraf kalemi recall ≥ %85 (eval), uydurma tutar 0 | R0.3 tercihen |
| R2.2b | LLM ile masraf kalemi genişletme (eşanlamlı/dolaylı ifadeler), alıntı zorunlu, tutar yine KB'den; `arac eval`'e masraf vakaları | ✅ b618df2: `masraf_kalemleri` (yalnız KB kodu, birebir alıntı, "yapıldı" diyen alıntı atılır), kural tabanlıyla birleşir. Canlı: 18 gerçek ilanda 3/3, 0 yanlış alarm; ana eval değişmedi (1,0/1,0) | Kural tabanlıya göre recall artışı ölçülür, uydurma tutar 0 | R0.3 |
| R2.3 | **B · Gerçek maliyet** hesabı (metin + km tetikli) → aralık + döküm; `offer.py` entegrasyonu | ✅ ön hesapta da (hak harcamaz); beyan kalemlerin alt tahmini teklifden düşülür, olası bakım yalnız gösterilir; panel "Tahmini gerçek maliyet". **Tutarlar R2.1 onayına kadar "onay bekliyor"** | Panelde "Tahmini gerçek maliyet: X–Y TL" + kalemler; teklif dayanağında görünür | R2.1, R2.2, R1.1 |

### R3 — Aday Karşılaştırma
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R3.1 | **Havuz**: "📌 Havuza ekle" (panel + rozet), yerel saklama, havuz görünümü (yan panel sekmesi), sil/temizle | ✅ 6bb1386 (panel düğmesi; rozet düğmesi yok) | Havuz yalnız `chrome.storage.local`; en fazla 10 ilan; sunucuya ilan verisi yazılmaz (test) | R0.2 |
| R3.2 | **Görülen fiyat geçmişi + ilan yaşı**: havuzdaki ilan her açılışta snapshot; "sizin gördüğünüz fiyatlar" | ✅ 3808e36 + 6bb1386 (ilan tarihi, kimden, sitenin "fiyatı değişti" bayrağı; fiyat geçmişi sitenin kendisinden İSTENMEZ) | Fiyat düşüşü yalnız kullanıcı gözleminden; dil dürüst | R0.2 (ilan tarihi), R3.1 |
| R3.3 | `POST /api/v1/compare`: deterministik tablo + LLM gerekçeli sıralama; sayı doğrulaması; 1 hak, aynı küme tekrar ücretsiz | ✅ 6bb1386 (`analysis/compare.py`, `tests/test_compare.py`; kararlar kodda, LLM yalnız gerekçe) | LLM çıktısındaki tablo dışı sayı içeren cümleler düşer (test); kota testleri | R3.1, R2.3 tercihen |
| R3.4 | **Karşılaştır ve Karar Ver** UI: tablo + 3 sonuç (galip / en riskli / pazarlık) + "önce bunu ekspertize götür" | ✅ 6bb1386 (e2e `test_war_room_pool_and_compare`, ekran görüntüsü kontrol edildi) | `frontend-design` ile; ekran görüntüsü kontrolü; e2e testi | R3.3 |

### R4 — Sinyaller ve likidite
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R4.1 | **2A · Aciliyet sinyalleri** (bant + alıntı) → teklif aralığına kural tabanlı etki | ✅ 1008db6: LLM'siz (`analysis/sinyaller.py`, `config/sinyaller.yaml`); metin + ilan yaşı + sitenin fiyat bayrağı + kullanıcının gördüğü düşüş → düşük/orta/yüksek; orta/yüksek yalnız açılış teklifini %1/%2 düşürür (`rules.yaml`). Tam kelime eşleşmesi ("açılır" ≠ "acil") | Eval'e aciliyet vakaları; skor değil bant; `rules.yaml` eşikleri | R0.3 tercihen |
| R4.2 | **2A · Ticari dil sinyali** (itham yok) → soru çarşafına madde | ✅ 1008db6: bireysel ilanda ≥2 farklı ticari ifade → "Ticari satıcı sinyali" + öncelik-1 soru; galeri ilanında yalnız bilgi. 18 gerçek ilanda 0 sinyal ("faturaları mevcut" yanlış alarmı giderildi) | "Sinyal" dili testle denetlenir (yasaklı kelimeler) | R1.4 |
| R4.3 | **2D · Likidite v0**: `likidite_kb.yaml` + emsal yoğunluğu + ilan yaşı → hızlı/orta/yavaş + gerekçe | ✅ taslak · 👤 KB onayı: 10 kural, hepsi onaysız (onaya kadar bant gösterilmez, yalnız emsal notu); gün sayısı asla söylenmez; `arac kb kontrol` | Gün sayısı söylenmez; gerekçe gösterilir | R0.2 |

### R5 — Güven ve görsel
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R5.1 | **F · Tramer yapıştır**: SBM metni parse + ilan beyanıyla çelişki bayrağı | ✅ 6dd51ee (R5.4 ile ortak "Belge röntgeni") · 👤 gerçek sorgu örnekleri: testler sentetik | Gerçek (maskeli) örneklerle parse testi; metin sunucuda saklanmaz | 👤 örnek metinler |
| R5.2 | **G · Görsel analiz** | ✅ belge fotoğrafı (cb314a5, kullanıcı onayı 2026-10-07): ekspertiz raporu / tramer fotoğrafı veya ekran görüntüsü (en fazla 4) → görüş modeli düz metne çevirir (kişisel alanları boş bırakır + regex maskeleme) → aynı alıntılı çıkarım. Canlı: eğik sentetik fotoğrafta tüm alanlar doğru, kişisel veri sızmadı. · ⬜ ilan fotoğraflarından boya/panel analizi ayrı araştırma (fotoğrafları yeniden indirmek kural 1 açısından değerlendirilmeli) | Gerçek belge fotoğraflarıyla doğrulama | 👤 örnekler |
| R5.4 | **I · Ekspertiz raporu röntgeni** (kullanıcı onayladı, 2026-10-07): kullanıcının fiziksel ekspertiz raporu (PDF/metin; v1 fotoğraf) → parça durumu sade dil, ilan beyanıyla çelişki listesi, masraf_kb ile onarım aralığı, güncellenmiş teklif, al/alma özeti. Rapor sunucuda saklanmaz; plaka/şasi/ad maskelenir; her bulgu rapordan alıntılı | ⬜ | Farklı firmalardan ≥5 maskeli gerçek rapor fixture'ı; parça okuma %100; tablo dışı sayı yok | ✅ v0 6dd51ee: `POST /api/v1/belge` (metin ya da metin katmanlı PDF, bellekte), kişisel veri maskeleme, alıntısız/uydurma bulgu ve belgede olmayan tutar atılır, ilanla kurallı karşılaştırma, onarım aralığı (onaylı KB), üst sınır önerisi; 1 hak, aynı belge ücretsiz; panel "Belge röntgeni". · 👤 3-5 gerçek rapor (farklı firma): testler sentetik. Fotoğraf/taranmış PDF → R5.2 |
| R5.3 | **H · Karar sonrası döngü**: havuzda "ekspertize gittim / aldım / almadım" → kalibrasyon raporu | ✅ c1bdce1: havuz kartında sonuç seçimi (yerel + bilerek gönderilen geri bildirim), `/yonetim/kalibrasyon` (etiket × sonuç, yanlış yeşil, kaçan aday). Kural bazında döküm yok: kural izi sunucuda saklanmaz | Yönetimde "hangi kural yanlış 🟢/🔴 üretti" raporu | R3.1 |

### Platform / operasyon (paralel)
| ID | Paket | Durum | Not |
|---|---|---|---|
| P.1 | Chrome Web Store "Özel" yayın + güvenilir test kullanıcıları + `STORE_URL` | 👤 | Paketleme/mağaza metinlerini ajan hazırlar, yükleme kullanıcının hesabından |
| P.2 | Davetliler için kullanım koşulları + KVKK aydınlatma metni (taslak → avukat) | ✅ taslak `docs/legal/` · 👤 `[...]` alanları + avukat; saklama süreleri kodda (`accounts.SAKLAMA`, günlük `prune`) | Hukuki tavsiye değildir notuyla taslak |
| P.3 | `feat/f0-eval` → `main` birleştirme ve push | 👤 | Push kullanıcıya ait (auto-mode engelleyebilir) |
| P.4 | Kanıt listesinde aynı bulgunun iki kez görünmesi (olumsuz sinyal + hard-claim) | ✅ c1bdce1 | Küçük UX düzeltmesi, `api.py:_kanitlar` |
| P.5 | Gmail/Outlook'ta HTML e-posta görünümü kontrolü (koyu mod dönüşümü) | 👤 | Kullanıcı ekran görüntüsü gönderir |
| P.6 | **CyberOto AI** yeniden adlandırma + logo | ✅ 31e42d3: tüm kullanıcıya görünen adlar, wordmark (Cyber beyaz + Oto #FF9A24), `design/brand/`. Teknik kimlikler değişmedi | — |
| P.7 | Alan adını `cyberoto.cybergene.co`'ya taşıma | ✅ 2026-10-07 canlı | `deploy/alan-adi-gecisi.sh` çalıştı: yeni site + Let's Encrypt (bitiş 2027-01-04, yenileme provası başarılı), `PUBLIC_URL` yeni adres; eski adres API'yi sunuyor (eski eklentiler), tarayıcıyı 301 ile yönlendiriyor. Eklenti 0.2.0 dağıtılınca kullanıcılar kendiliğinden geçer. Tüm kullanıcılar 0.2.0+ olunca eski site kaldırılabilir |

## 6. Hak (kredi) ekonomisi — yeni özellikler

| Eylem | Hak | Gerekçe |
|---|---|---|
| İlan açmak (ön hesap) | 0 | Kullanıcı kararı |
| Yapay zeka röntgeni | 1 | Aynı ilan + aynı açıklama 7 gün ücretsiz |
| Soru çarşafı, araca özel liste, gerçek maliyet | 0 (röntgene dahil) | Röntgen sonucundan türetilir |
| Karşılaştır ve karar ver (2-5 ilan) | 1 | Aynı küme tekrar ücretsiz; her ilanın röntgeni önkoşul |
| Belge röntgeni (ekspertiz raporu / tramer) | 1 | Aynı belge + ilan tekrar ücretsiz; LLM hatasında iade |
| Satış/piyasa sinyalleri | 0 | Kurallı, ön hesapta da çalışır |
| Görsel röntgen | Açık karar | Maliyeti ölçülünce |

## 7. Açık kararlar (kullanıcıya sorulacak — tahmin etme)

1. **Eklenti 0.2.0 dağıtımı** (yeni adres + belge fotoğrafı). Alan adı geçişi canlıda tamam.
2. **Gerçek belgeler**: farklı firmaların ekspertiz raporu fotoğrafları + tramer ekran görüntüleri (kullanıcı arıyor) → R5.1/R5.2/R5.4 gerçek fixture testi. Fotoğraf okuma hazır.
3. **Yasal metinler** (P.2): `[...]` alanları + avukat (kullanıcıda).
4. Push, Chrome Web Store "Özel" yayın, e-posta görünüm kontrolü (P.1, P.3, P.5).

Onaylananlar (2026-10-07, sohbette): masraf_kb 42 kalem, likidite_kb 10 kural, R0.3 18 vaka (3 sınırda dahil), rules.yaml %1/%2 açılış indirimi, alan adı taşıma, görsel analiz.

(7 Ekim 2026 öncesi kararlar → §8.)

### Dil kılavuzu (aciliyet ve satıcı sinyalleri — kullanıcı kararı)
Finansal, analitik, objektif dil. İtham ya da fırsatçılık çağrışımı **yasak**; testle denetlenir (yasaklı kelime listesi).

| Kullanma | Kullan |
|---|---|
| Panik satıcı, çaresiz, zor durumda | **Hızlı satış motivasyonu** |
| Fırsat, kelepir, kap | **Yüksek indirim ivmesi**, **pazarlık payı geniş** |
| Gizli alsatçı, sahtekâr | **Ticari satıcı sinyali** |
| Dolandırıcı | **Dolandırıcılık kalıbı riski** (yalnız kalıp, kişi değil) |

## 8. Karar kaydı

| Tarih | Karar | Kaynak |
|---|---|---|
| 2026-10-06 | Geniş lansman yok; önce davetli kapalı B2C beta, geri bildirim, sonra yayın | Kullanıcı |
| 2026-10-06 | Sistem kopyalanamamalı: beyin sunucuda, eklenti ince istemci, kural ağırlıkları (trace) yalnız sahibe | Kullanıcı + Claude |
| 2026-10-06 | Ürün CyberGene markası altında; alan adı `otoxray.cybergene.co` | Kullanıcı |
| 2026-10-06 | Giriş e-posta koduyla; yönetim web sayfasından | Kullanıcı |
| 2026-10-06 | İlan açmak hak harcamaz; röntgen düğmeyle; aynı ilan 7 gün ücretsiz | Kullanıcı + Claude |
| 2026-10-06 | Bu dosyadaki R0→R5 sırası ve §2 kuralları | Claude önerisi; kullanıcı onayladı (7 Ekim) |
| 2026-10-07 | Havuz en fazla **10 ilan** | Kullanıcı |
| 2026-10-07 | Karşılaştırma **1 hak**; her ilanın önce tekil röntgeni çekilmiş olmalı | Kullanıcı |
| 2026-10-07 | KB'leri (models/masraf/likidite) **Claude taslaklar** (fiyat aralıkları dahil), **kullanıcı son onayı verir** (gerekirse ustaya danışır) | Kullanıcı |
| 2026-10-07 | Aciliyet dili finansal/analitik/objektif (§7 dil kılavuzu) | Kullanıcı |
| 2026-10-07 | Görsel analiz (R5.2) bütçesi askıda; metin tabanlı analizler bitince değerlendirilecek | Kullanıcı |
| 2026-10-07 | Ham örnek sayfalar `data/samples/` (git dışı); temizlenmiş fixture `tests/fixtures/real/` | Claude, kullanıcı ile |
| 2026-10-07 | KB'ler (masraf 42, likidite 10), R0.3 18 vaka, R4 eşikleri onaylandı; alan adı `cyberoto.cybergene.co` | Kullanıcı |
| 2026-10-07 | Ekspertiz raporu analizi plana alındı (R5.4), Tramer ile tek "Belge röntgeni"; kalan tüm işler otonom tamamlansın | Kullanıcı |
| 2026-10-07 | Ürün adı **CyberOto AI** (kısa: CyberOto); CyberGene projeleri "Cyber + alan" kalıbıyla adlandırılır. Yeniden adlandırma altyapı bitince yapılır; alan adı değişikliği kullanıcıya sorulur; logo kullanıcıdan gelecek | Kullanıcı |

## 9. Devir protokolü (kota biterse / ajan değişirse)

1. Yarım kalan paketi **⬜'ye geri çekme**; `🔄` bırak ve günlükte "nerede kaldım, sıradaki adım, açık sorun" yaz.
2. Commit edilmemiş iş bırakma: küçük, testi geçen commit'ler at (`Co-Authored-By` satırıyla). Testi geçmeyen deneme dalına (`wip/...`) gider.
3. Canlıya yalnız testleri geçmiş, commit edilmiş kodu `deploy/redeploy.sh` ile gönder; sonra `/healthz` ve ilgili uç noktayı canlıda doğrula.
4. Sır/anahtar bu dosyaya, günlüğe ya da commit'e **asla** yazılmaz. Sunucu `.env` değerlerini kullanıcı girer.
5. Kullanıcı kararı gereken yerde dur, **Açık kararlar**a ekle, sor.
6. LLM'e dokunan her değişiklikte `arac eval --json` öncesi/sonrası sonucu günlüğe yaz.

## 10. İlerleme günlüğü

| Tarih | Ajan | Paket | Not |
|---|---|---|---|
| 2026-10-07 | Claude (5d82b169) | Chrome Web Store gönderildi | Liste dışı, paket `dist/cyberoto-eklenti-0.2.0.zip`; geliştirici kimlik doğrulaması tamam. İnceleyici için `inceleme@cybergene.co` deneme üyesi (10/gün, 60/ay, 60 gün; cihaz anahtarı yalnız mağaza formunda). **Bekleyen:** Google onayı (1-3 iş günü) → mağaza bağlantısı gelince sunucu `.env`'e `STORE_URL=` + `sudo systemctl restart otoxray`; davet düğmesi "Chrome'a ekle" olur. İnceleme bitince `inceleme@` üyesini iptal et. Onaylanana kadar sunucu adresi/`/api/v1` sözleşmesi değiştirilmez. |
| 2026-10-07 | Claude (5d82b169) | Web + yönetim + Jeff API | cc731fc tanıtım sayfası (/) · 37a9297 yönetici şifresi (`arac xray admin-sifre`, kullanıcı kendisi belirler; kod hatası: yalnız en son kod geçerli) · f7a2d8f /kurulum + eklenti zip, davet e-postasında tek tık, gerçek CyberGene ikonu, tanıtım sayfasında gerçek panel görselleri (`scripts/tanitim_gorselleri.py`), "Savaş odası" → "Aday karşılaştırma" · 8cdcae4 Jeff yönetici API'si (`/admin-api/v1`, yalnız 127.0.0.1 + `ADMIN_API_TOKEN`, işlem kaydı; anahtar sunucuda `~hermes/.config/cyberoto/`, rehber `deploy/JEFF_ADMIN_API.md`). 464 test. |
| 2026-10-07 | Claude (5d82b169) | Alan adı ✅, R5.2 belge fotoğrafı ✅ | DNS doğrulandı (yerel + sunucu), geçiş betiği çalıştı; yeni/eski adres, yönetim, e-posta logosu, sertifika ve yenileme provası tek tek doğrulandı. cb314a5 görsel okuma: canlı sunucuda sahip anahtarıyla fotoğraf testi başarılı. 457 test. **Sıradaki:** eklenti 0.2.0 dağıtımı (kullanıcı), gerçek belge örnekleri. |
| 2026-10-07 | Claude (5d82b169) | Onaylar + alan adı hazırlığı | 7f3e6b4 KB/eval onayları yayında (tutarlar ve piyasa hızı bandı etkin). Alan adı: eklenti 0.2.0 + `deploy/alan-adi-gecisi.sh` + nginx şablonları; sunucu `.env` iki adı kabul eder. Canlı hata bulundu ve düzeltildi: nginx gövde sınırı 256k idi, belge röntgeni PDF'leri 413 alırdı → 8m. **Bekleyen:** DNS A kaydı. |
| 2026-10-07 | Claude (5d82b169) | R4, R5, R0.3/R0.4, R2.2b, P.2/P.4, yeniden adlandırma ✅ | 1008db6 R4 sinyaller + likidite · 6dd51ee belge röntgeni (pypdf) · c1bdce1 kalibrasyon + kanıt tekrarı · f9c1c3b Python ayrıştırıcı gerçek yapıda · e94011f gerçek vaka taslakları · b618df2 LLM masraf kalemleri · 643d158/6363cb2 saklama temizliği + yasal taslaklar · 31e42d3 CyberOto AI. 450 test, 31e42d3 yayında. Eval (canlı LLM): ana 50 vaka 1,0/1,0; gerçek taslak 18 vaka 1,0/1,0. Not: kullanıcının `rapor.md` dosyası yanlışlıkla bir commit'e girdi; commit'ten ve sunucudan çıkarıldı (yerelde duruyor, izlenmiyor). **Sıradaki:** §7 kullanıcı girdileri. |
| 2026-10-07 | Claude (5d82b169) | R3 ✅ | Aday Karşılaştırma: havuz (yalnız tarayıcıda, en fazla 10), görülen fiyat ve ilan yaşı, `/api/v1/compare` (kurallı seçimler + doğrulanmış anlatım + şablon yedeği, üye için tekil röntgen önkoşulu, aynı küme ücretsiz), panel "Havuz" sekmesi. 400 test, 6bb1386 yayında. Kullanıcı yeni fikir: ekspertiz raporu analizi → R5.4 öneri, §7'de karar bekliyor. **Sıradaki:** R4.1 aciliyet sinyalleri; altyapı bitince CyberOto AI yeniden adlandırması. |
| 2026-10-06 | Claude (5d82b169) | — | Ar-Ge planı oluşturuldu. Mevcut durum: kapalı beta canlı (d5b97cb). Sıradaki: R0.1 (kullanıcıdan gerçek sayfalar), paralelde R1.1 taslağı ve R1.3. |
| 2026-10-07 | Claude (5d82b169) | R1.1/R1.3 onay, R2 | Kullanıcı R1.1 (32 model) ve R1.3'ü sohbette toplu onayladı (kaynak alanlarına işlendi). R2.1 masraf_kb taslağı (42 kalem). R2.2 planı değişti: LLM yerine önce kural tabanlı bulucu (alıntılı, ön hesapta da çalışır); LLM genişletmesi R2.2b. R2.3 gerçek maliyet + teklif düşümü + panel kartı. 389 test. **Sıradaki:** kullanıcıdan masraf_kb onayı; sonra R3 (Aday Karşılaştırma). |
| 2026-10-07 | Claude (5d82b169) | R1.2 ✅, R1.4 ✅ | Araca özel ekspertiz listesi ve soru çarşafı (`analysis/checklist.py`), API `ekspertiz`/`soru_carsafi`/`soru_metni`, panel bölümleri; 8 birim + e2e. 364 test. **R1 durumu:** R1.1 ve R1.3 taslakları kullanıcı onayı bekliyor (onaylanınca kronik/bakım maddeleri ve alım günü listesi görünür). **Sıradaki ajan:** onay gelirse `arac kb kontrol` → yayın; yoksa R2.1 `masraf_kb.yaml` taslağı (aralıklar, kaynak/tarih, onaysız). |
| 2026-10-07 | Claude (5d82b169) | R0 ✅ | 2. tur örnekler (3 arama, 2 galeriden, 3 boş şemalı) işlendi. Boş şema = "orijinal" sanma hatası anlam düzeyinde çözüldü (`diagram_check.py`, 22 birim testi). Arama: seri/marka okuma, model karışması, reklam satırı düzeltildi. Kullanıcı isteği: arama çubuğu sayfa geçişi/geri dönüşte kayboluyordu → kalıcı + CyberGene tasarımı. 356 test. **R0 tamam; R1'e geçiliyor.** |
| 2026-10-07 | Claude (5d82b169) | R0.1, R0.2 | 13 gerçek ilan temizlenip `tests/fixtures/real`'e alındı (satıcı/hesap blokları, telefon, plaka, harita koordinatı silindi; hesap adı 0 eşleşme). Eklenti detay okuması 13/13 doğrulandı; **hasar şeması okunmuyordu (tüm gerçek ilanlar 🟢 alamıyordu) → düzeltildi**. KB şanzıman maddeleri vites+model+yıl eşleşmesine geçti. `tests/test_real_pages.py` (19 test). 324 test. Bulgular §3b. Sıradaki: kullanıcıdan 3 arama sayfası + galeriden/belirtilmemiş örnekler; R0.3 için 13 açıklamanın etiket taslağı; ilan tarihi okuma. |
| 2026-10-07 | Claude (5d82b169) | R1.1, R1.2, R1.3 | Kararlar §8'e işlendi. R1.1: `models_kb.yaml` 32 model/59 madde taslak (hepsi onaysız → etkisiz). Yükleyici yeniden yazıldı (onay filtresi, Türkçe harf katlama, motor/vites/yakıt/yıl, km eşiği, bakım). Puan: yalnız yüksek ciddiyet + tetiklenmiş kronik (eskiden her eşleşme -0.5). R1.3: `alim_gunu.yaml` + `/api/v1/rehber` + panel bölümü. `arac kb kontrol` eklendi. 303 test. **Sıradaki ajan için:** kullanıcı onaylarını bekle; onay gelince `arac kb kontrol` → yayın. R0.1 sayfaları gelince R0.2'ye geç. Bekleme sırasında yapılabilecek: R2.1 `masraf_kb.yaml` taslağı (aralıklar, kaynak/tarih, onaysız). |
