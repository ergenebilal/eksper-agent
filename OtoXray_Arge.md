# otoXray — Ar-Ge Planı ve Takip Dosyası

> **Bu dosya canlı takip dosyasıdır.** İşi devralan her ajan (Claude, Codex, başka bir model) önce bu dosyayı,
> sonra `CLAUDE.md`'yi okur. İş paketini başlatırken durumunu `🔄`, bitirince `✅` yapar ve en alttaki
> **İlerleme günlüğü**ne bir satır ekler. Kararı kullanıcıya ait konular **Açık kararlar** bölümündedir: tahmin edilmez, sorulur.

Son güncelleme: 2026-10-07 · Hazırlayan: Claude (oturum 5d82b169)

---

## 0. Devralan ajan için 5 dakikalık başlangıç

1. `git status`, `git log --oneline -5`. Çalışma dalı: **`feat/f0-eval`** (main'e göre ~38 commit önde, **push edilmedi**, push kullanıcıya ait).
2. Testler: `uv run pytest -q` (≈50 sn, ≈290 test; `tests/test_extension_e2e.py` gerçek Chromium ister: `uv run playwright install chromium`).
3. Canlı sistem: `https://otoxray.cybergene.co` (sağlık: `/healthz`). Yayın: `bash deploy/redeploy.sh` (yalnız **commit edilmiş** kodu gönderir).
4. Ayrıntılı altyapı: [deploy/README.md](deploy/README.md) · ürün kararları: [PLAN.md](PLAN.md) · tasarım tokenları: [design/cybergene-dna.json](design/cybergene-dna.json).
5. Bir sonraki iş: **§5 Yol haritası**ndaki ilk `⬜` paket (önkoşullara bak).

## 1. Ürün ve mevcut durum (6 Ekim 2026)

**otoXray AI** — CyberGene ürünü. Kullanıcının kendi tarayıcısında açtığı araç ilanını okuyan Chrome eklentisi + sunucu.
🟢 = "ekspertize götürmeye değer", **"satın al" değil**. Kapalı B2C beta: davetli kullanıcılar, kişiye özel haklar.

| Bileşen | Durum | Yer |
|---|---|---|
| Eklenti (MV3): ilan sayfası okuma, yan panel karnesi, arama sayfası fiyat rozetleri | ✅ çalışıyor, **seçiciler gerçek sayfayla DOĞRULANMADI** | `extension/` |
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

Kullanıcının önerileri (1: Savaş Odası, 2A–2E) aşağıda **değer / risk / bizim kısıtlarımızla uyum** açısından değerlendirildi.
Özet: hepsi doğru yönde. En yüksek değer/maliyet oranı **E (araca özel ekspertiz)**, **C (soru çarşafı)** ve **B (gerçek maliyet)**;
**Savaş Odası** ürünü "tek ilan aracı"ndan "karar aracı"na çeviren ana özellik. **D (likidite)** ve **gizli alsatçı** veri eksikliği nedeniyle
dürüst sınırlarla, düşük güvenle başlamalı.

### 1 · Savaş Odası (Havuz + Karşılaştır ve Karar Ver) — ⭐ ana özellik
- **Neden güçlü:** Gerçek alıcı tek ilana değil, 3-5 aday arasında karar verir. Bugün otoXray her ilanı tek başına puanlıyor; karşılaştırma eksik.
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
  - Fiyat düşüşü sinyali yalnızca kullanıcının kendi gözlemlerinden (Savaş Odası snapshot'ları).
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
- **H · Karar sonrası döngü:** "Ekspertize gittim → sonuç", "aldım/almadım" → hem kalibrasyon hem likidite verisi. Geri bildirim altyapısı var; Savaş Odası'na "durum" alanı olarak bağlanır.
- **I · Gerçek ilan doğrulaması (ÖNKOŞUL):** Yukarıdaki her şey eklentinin gerçek sayfayı doğru okumasına bağlı. Seçiciler hâlâ sentetik sayfalarla test ediliyor. **Bu, R0 paketidir ve her şeyden önce gelir.**

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
| R0.1 | 15-20 gerçek ilan sayfası (farklı marka, galeri/sahibinden, diyagramlı/diyagramsız) + 3 arama sayfası | 👤 | Kullanıcı "Farklı kaydet" ile **`data/samples/`** klasörüne koyar (git'e girmez, ham kalır); ajan `arac fixture sanitize data/samples/*.html` ile temizleyip `tests/fixtures/real/`'a alır | `fixture_sanitizer.py` |
| R0.2 | Eklenti seçicilerini gerçek fixture'lardan çıkar (UNVERIFIED işaretlerini kaldır) + **ilan tarihi** alanı | ⬜ | Tüm gerçek fixture'larda zorunlu alanlar %100 okunur; e2e gerçek fixture ile koşar | `extension/lib/selectors.js`, `extract-*.js`, `tests/test_extension_e2e.py` |
| R0.3 | Gerçek açıklamalardan 100+ etiketli vaka (`kaynak: gercek`) | 👤/⬜ | `arac eval` recall ≥ %90, temiz vakada 🟢 engeli ≤ %5 | `tests/data/aciklamalar.jsonl` |

### R1 — Hızlı kazanımlar (mevcut veriden)
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R1.1 | `models_kb.yaml` ilk 30 model: kronik arıza + km eşiği + bakım aralığı (LLM taslak → kullanıcı onayı) | ✅ taslak · 👤 onay | 32 model / 59 madde, hepsi `onayli: false`; şema + onay kuralı testli; `arac kb kontrol` | — |
| R1.2 | **E · Araca özel ekspertiz listesi**: kronik + km tetikli + bulgudan türeyen maddeler, öncelik sıralı | 🔄 | ✅ Motor/vites/yakıt/yıl filtresi, km eşiği, bakım zamanı, öncelik sırası, puana yalnız yüksek+tetikli (`models_kb.ekspertiz_maddeleri`). Kalan: bulgudan türeyen maddeler + panelde ayrı "Bu araçta özellikle" başlığı. Etki R1.1 onayından sonra başlar | R1.1 |
| R1.3 | **E+ · Alım günü / noter listesi** (statik, hukuki tavsiye değildir notu) | ✅ taslak · 👤 onay | `config/alim_gunu.yaml` (5 bölüm), `GET /api/v1/rehber`, panelde açılır bölüm; onaylanınca görünür | — |
| R1.4 | **C · Soru çarşafı**: veri boşlukları + bulgular → öncelikli sorular + "cevap şuysa" + kopyala | ⬜ | Her soru bir veri boşluğuna/bulguya bağlı (izlenebilir); ek hak yok; testli şablon | R1.2 (kısmen) |

### R2 — Gerçek maliyet
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R2.1 | `masraf_kb.yaml`: ~40 yaygın kalem × segment, min-max TL, tarih, kaynak (kullanıcı onaylı) | ⬜ (+👤) | Şema testi; tarihi 6 aydan eski kalem uyarı verir | — |
| R2.2 | LLM şemasına `masraf_kalemleri` (Evidence) + jargon; eval'e masraf vakaları | ⬜ | Masraf kalemi recall ≥ %85 (eval), uydurma tutar 0 | R0.3 tercihen |
| R2.3 | **B · Gerçek maliyet** hesabı (metin + km tetikli) → aralık + döküm; `offer.py` entegrasyonu | ⬜ | Panelde "Tahmini gerçek maliyet: X–Y TL" + kalemler; teklif dayanağında görünür | R2.1, R2.2, R1.1 |

### R3 — Savaş Odası
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R3.1 | **Havuz**: "📌 Havuza ekle" (panel + rozet), yerel saklama, havuz görünümü (yan panel sekmesi), sil/temizle | ⬜ | Havuz yalnız `chrome.storage.local`; en fazla 10 ilan; sunucuya ilan verisi yazılmaz (test) | R0.2 |
| R3.2 | **Görülen fiyat geçmişi + ilan yaşı**: havuzdaki ilan her açılışta snapshot; "sizin gördüğünüz fiyatlar" | ⬜ | Fiyat düşüşü yalnız kullanıcı gözleminden; dil dürüst | R0.2 (ilan tarihi), R3.1 |
| R3.3 | `POST /api/v1/compare`: deterministik tablo + LLM gerekçeli sıralama; sayı doğrulaması; 1 hak, aynı küme tekrar ücretsiz | ⬜ | LLM çıktısındaki tablo dışı sayı içeren cümleler düşer (test); kota testleri | R3.1, R2.3 tercihen |
| R3.4 | **Karşılaştır ve Karar Ver** UI: tablo + 3 sonuç (galip / en riskli / pazarlık) + "önce bunu ekspertize götür" | ⬜ | `frontend-design` ile; ekran görüntüsü kontrolü; e2e testi | R3.3 |

### R4 — Sinyaller ve likidite
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R4.1 | **2A · Aciliyet sinyalleri** (bant + alıntı) → teklif aralığına kural tabanlı etki | ⬜ | Eval'e aciliyet vakaları; skor değil bant; `rules.yaml` eşikleri | R0.3 tercihen |
| R4.2 | **2A · Ticari dil sinyali** (itham yok) → soru çarşafına madde | ⬜ | "Sinyal" dili testle denetlenir (yasaklı kelimeler) | R1.4 |
| R4.3 | **2D · Likidite v0**: `likidite_kb.yaml` + emsal yoğunluğu + ilan yaşı → hızlı/orta/yavaş + gerekçe | ⬜ (+👤 KB onayı) | Gün sayısı söylenmez; gerekçe gösterilir | R0.2 |

### R5 — Güven ve görsel
| ID | Paket | Durum | Kabul ölçütü | Önkoşul |
|---|---|---|---|---|
| R5.1 | **F · Tramer yapıştır**: SBM metni parse + ilan beyanıyla çelişki bayrağı | ⬜ | Gerçek (maskeli) örneklerle parse testi; metin sunucuda saklanmaz | 👤 örnek metinler |
| R5.2 | **G · Görsel röntgen** araştırması: model seçimi, maliyet, eval seti | ⬜ | Ar-Ge raporu + karar (kullanıcı) | — |
| R5.3 | **H · Karar sonrası döngü**: havuzda "ekspertize gittim / aldım / almadım" → kalibrasyon raporu | ⬜ | Yönetimde "hangi kural yanlış 🟢/🔴 üretti" raporu | R3.1 |

### Platform / operasyon (paralel)
| ID | Paket | Durum | Not |
|---|---|---|---|
| P.1 | Chrome Web Store "Özel" yayın + güvenilir test kullanıcıları + `STORE_URL` | 👤 | Paketleme/mağaza metinlerini ajan hazırlar, yükleme kullanıcının hesabından |
| P.2 | Davetliler için kullanım koşulları + KVKK aydınlatma metni (taslak → avukat) | ⬜ | Hukuki tavsiye değildir notuyla taslak |
| P.3 | `feat/f0-eval` → `main` birleştirme ve push | 👤 | Push kullanıcıya ait (auto-mode engelleyebilir) |
| P.4 | Kanıt listesinde aynı bulgunun iki kez görünmesi (olumsuz sinyal + hard-claim) | ⬜ | Küçük UX düzeltmesi, `api.py:_kanitlar` |
| P.5 | Gmail/Outlook'ta HTML e-posta görünümü kontrolü (koyu mod dönüşümü) | 👤 | Kullanıcı ekran görüntüsü gönderir |

## 6. Hak (kredi) ekonomisi — yeni özellikler

| Eylem | Hak | Gerekçe |
|---|---|---|
| İlan açmak (ön hesap) | 0 | Kullanıcı kararı |
| Yapay zeka röntgeni | 1 | Aynı ilan + aynı açıklama 7 gün ücretsiz |
| Soru çarşafı, araca özel liste, gerçek maliyet | 0 (röntgene dahil) | Röntgen sonucundan türetilir |
| Karşılaştır ve karar ver (2-5 ilan) | 1 | Aynı küme tekrar ücretsiz; her ilanın röntgeni önkoşul |
| Tramer yapıştır | 0 (öneri) | Güveni artırır, LLM'siz parse hedefi |
| Görsel röntgen | Açık karar | Maliyeti ölçülünce |

## 7. Açık kararlar (kullanıcıya sorulacak — tahmin etme)

_Şu an açık karar yok._ (7 Ekim 2026'da tümü yanıtlandı → §8.) Yeni karar gerektiğinde buraya ekle ve kullanıcıya sor.

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
| 2026-10-06 | Claude (5d82b169) | — | Ar-Ge planı oluşturuldu. Mevcut durum: kapalı beta canlı (d5b97cb). Sıradaki: R0.1 (kullanıcıdan gerçek sayfalar), paralelde R1.1 taslağı ve R1.3. |
| 2026-10-07 | Claude (5d82b169) | R1.1, R1.2, R1.3 | Kararlar §8'e işlendi. R1.1: `models_kb.yaml` 32 model/59 madde taslak (hepsi onaysız → etkisiz). Yükleyici yeniden yazıldı (onay filtresi, Türkçe harf katlama, motor/vites/yakıt/yıl, km eşiği, bakım). Puan: yalnız yüksek ciddiyet + tetiklenmiş kronik (eskiden her eşleşme -0.5). R1.3: `alim_gunu.yaml` + `/api/v1/rehber` + panel bölümü. `arac kb kontrol` eklendi. 303 test. **Sıradaki ajan için:** kullanıcı onaylarını bekle; onay gelince `arac kb kontrol` → yayın. R0.1 sayfaları gelince R0.2'ye geç. Bekleme sırasında yapılabilecek: R2.1 `masraf_kb.yaml` taslağı (aralıklar, kaynak/tarih, onaysız). |
