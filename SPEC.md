# SPEC.md — Araç Eksper Ajanı Teknik Şartnamesi

## 1. Veri modelleri (Pydantic)

```python
class PartState(str, Enum):
    ORIGINAL = "orijinal"; LOCAL_PAINT = "lokal_boyali"; PAINTED = "boyali"
    REPLACED = "degisen"; UNKNOWN = "belirtilmemis"

class SearchCriteria(BaseModel):
    marka: str; model: str; seri: str | None = None
    max_butce: int; min_butce: int | None = None
    min_yil: int | None = None; max_km: int | None = None
    vites: Literal["manuel","otomatik","yari_otomatik"] | None = None
    yakit: Literal["benzin","dizel","lpg","hibrit","elektrik"] | None = None
    il: str | None = None
    kimden: Literal["sahibinden","galeriden","hepsi"] = "hepsi"

class ListingSummary(BaseModel):   # liste sayfasından
    ilan_no: str; url: str; baslik: str; fiyat: int
    yil: int; km: int; il: str; ilce: str | None; ilan_tarihi: date

class ListingDetail(ListingSummary):  # detay sayfasından
    seri: str | None; paket: str | None; vites: str | None; yakit: str | None
    kasa_tipi: str | None; motor_hacmi: str | None; renk: str | None
    kimden: str | None
    agir_hasar_kayitli: bool | None
    parts: dict[str, PartState]          # sahibinden boya/değişen diyagramı
    tramer_tutari_yapilandirilmis: int | None   # sayfada alan olarak varsa
    aciklama: str
    fetched_at: datetime
    raw_html_path: str                   # debug ve yeniden parse için

class DescriptionFindings(BaseModel):  # LLM çıktısı
    tramer_tutari: int | None
    sase_direk_podye_islem: Literal["yok_beyan","var","belirsiz"]
    airbag: Literal["orijinal_beyan","acmis","belirsiz"]
    motor_sanziman: Literal["sorunsuz_beyan","degisen","sorunlu","belirsiz"]
    km_degisimi_suphesi: bool
    olumlu_sinyaller: list[Evidence]      # ilk sahibinden, servis bakımlı, faturalı...
    olumsuz_sinyaller: list[Evidence]     # podye ucu, sandık motor, takas fiyatı...
    dolandiricilik_sinyalleri: list[Evidence]  # kapora, yurt dışı, kargo, acil+çok ucuz
    belirsiz_ifadeler: list[Evidence]     # "ufak tefek", "makyajlı", "hatasız gibi"

class Evidence(BaseModel):
    etiket: str; alinti: str   # alıntı açıklamada birebir geçmeli (doğrulanır)

class Verdict(BaseModel):
    ilan_no: str
    etiket: Literal["ALINIR","DUSUNULEBILIR","ALINMAZ"]
    guven_skoru: float          # 0-10
    veri_tamlik: float          # 0-1, skorun ne kadar güvenilir olduğu
    hard_fails: list[str]
    artilar: list[str]; eksiler: list[str]
    piyasa: MarketStats | None
    tavsiye_teklif: int | None
    ekspertiz_kontrol_listesi: list[str]
```

## 2. Toplama katmanı (Faz 1)

### 2.1 URL oluşturucu — `collector/url_builder.py`
- `build_search_url(criteria, page:int=1, sort="date_desc") -> str`
- Kategori slug'ı (marka/model/seri) `config/category_map.yaml`'dan gelir. İlk sürümde harita elle doldurulur; yardımcı komut `arac map add` ile kullanıcı bir sahibinden arama URL'sini yapıştırır, slug çıkarılıp haritaya eklenir.
- Query parametreleri (fiyat, yıl, km, sıralama, sayfalama) gerçek sahibinden URL'lerinden çıkarılıp sabitlere yazılır; testler bu örnek URL'lerle doğrulanır.
- Kabul: 5 farklı kriter seti için üretilen URL, elle oluşturulmuş referans URL ile birebir eşleşir.

### 2.2 Toplayıcı arayüzü — `collector/base.py`
```python
class Collector(Protocol):
    async def fetch_list(self, url: str) -> FetchResult
    async def fetch_detail(self, url: str) -> FetchResult
class FetchResult(BaseModel):
    status: Literal["OK","BLOCKED","NOT_FOUND","ERROR"]
    html: str | None; final_url: str; saved_path: str | None
```

### 2.3 PlaywrightCollector
- Persistent context, kullanıcının kendi oturum açtığı profil dizini (`BROWSER_PROFILE_DIR`), headed mod.
- Ev/mobil internet üzerinde çalışacak şekilde tasarlanır (VPS'te değil). VPS yalnızca bildirim ve raporlama tarafını çalıştırabilir.
- Her istek arası `random.uniform(8, 20)` sn; detay sayfasında doğal okuma için sayfa sonuna kadar yumuşak kaydırma.
- Global rate limiter (token bucket, DB'de kalıcı) — `MAX_PAGES_PER_HOUR`.
- Engel tespiti: HTTP 403/429, bilinen doğrulama sayfası işaretleri (`parser/selectors.py: BLOCK_MARKERS`), beklenen ana elementin yokluğu → `BLOCKED`.
- `BLOCKED` sonrası: üstel backoff (30 dk, 2 sa, 6 sa), Telegram bildirimi, ardışık 3 blokta watcher'lar otomatik duraklatılır.
- Her ham HTML `data/raw/{ilan_no}/{timestamp}.html` olarak saklanır (gzip).

### 2.4 ManualImportCollector (yedek yol)
- `arac import <dosya.html>` veya klasör: tarayıcıdan "Farklı kaydet" ile alınmış sayfaları parse eder.
- Engel durumunda sistem bu yolla çalışmaya devam edebilir. Değerlendirme hattı toplama yönteminden bağımsızdır.

## 3. Parser — `parser/`
- `list_parser.parse(html) -> list[ListingSummary]` ve sonraki sayfa linki.
- `detail_parser.parse(html) -> ListingDetail`
- `damage_parser.parse(html) -> dict[str, PartState]`: Parça adları normalize edilir (`sol_on_camurluk`, `motor_kaputu`, `tavan`, `on_tampon` ...). Sayfada olmayan parça → `UNKNOWN`.
- Fiyat/km metinleri: "845.000 TL" → 845000, "125.000 km" → 125000.
- Kabul: en az 10 detay fixture'ı (farklı marka, galeri/sahibinden, diyagramlı/diyagramsız) %100 alan doğruluğuyla parse edilir.

## 4. Analiz motoru (Faz 2)

### 4.1 Açıklama röntgeni — `analysis/description_llm.py`
- Girdi: `aciklama` + başlık + yapılandırılmış alanlar. Çıktı: `DescriptionFindings`.
- Sistem promptu: Türk ikinci el araç piyasası jargonu sözlüğü (`config/jargon.yaml`) enjekte edilir. Örnekler: "podye", "şase ucu", "direk", "sandık motor", "kafa yapıldı", "bedelsiz", "çekme belgeli", "sigorta şişirmesi", "takas fiyatı farklı", "hatasız" vs "hatasız gibi", "kaporta temiz" (boya bilgisi vermez).
- Kanıt doğrulama: her `Evidence.alinti` normalize edilmiş açıklamada substring olarak aranır; bulunamazsa bulgu düşürülür ve loglanır.
- Ucuz model ile ilk geçiş, yalnızca kırmızı bayrak veya belirsizlik varsa güçlü model ile ikinci geçiş (maliyet kontrolü).
- Sonuç `ilan_no + sha256(aciklama)` ile cache'lenir.
- Kabul: 30 etiketli açıklamalık mini veri setinde kırmızı bayrak recall ≥ %90.

### 4.2 Piyasa analizi — `analysis/market.py`
- Emsal kümesi: aynı marka/model/seri, yıl ±1, aynı vites ve yakıt, km bandı ±%30. Paket eşleşmesi varsa ağırlık 1.0, yoksa 0.7.
- Kaynak: DB'deki son 30 gün içindeki aktif ilanlar. Yetersizse (n < 8) arama bir kez genişletilir (yıl ±2, km bandı ±%50) ve `guven: "dusuk"` işaretlenir.
- Çıktı: `MarketStats(n, medyan, p25, p75, guven)`. Aykırı değerler IQR ile atılır.
- Hesap: `sapma = (fiyat - medyan) / medyan`.
- Not: Bunlar talep fiyatlarıdır, gerçek satış fiyatı değildir. Raporda "piyasa ilan medyanı" ifadesi kullanılır.

### 4.3 Kural motoru — `analysis/rules_engine.py`
Eşikler `config/rules.yaml`'da. Varsayılanlar:

**Hard fail (doğrudan 🔴):**
- `agir_hasar_kayitli == True` veya açıklamada pert/çekme belgeli/ağır hasar
- `sase_direk_podye_islem == "var"`
- `airbag == "acmis"`
- `tavan` parçası boyalı veya değişen
- Fiyat > `max_butce`
- `sapma > +0.25`
- Yıllık km > 45.000
- Dolandırıcılık sinyali ≥ 1 ve `sapma < -0.20`

**Puanlama (10'dan düşülür):**
| Durum | Puan |
|---|---|
| Lokal boyalı parça (her biri) | -0.3 |
| Boyalı parça (her biri) | -0.6 |
| Değişen parça (kapı/çamurluk) | -1.2 |
| Değişen kaput veya bagaj | -1.5 |
| Tampon boya/değişen | -0.1 (kozmetik) |
| `UNKNOWN` parça (her biri, max -1.5) | -0.25 |
| Tramer / tahmini araç değeri 0–%5 | -0.3 |
| %5–%10 | -1.0 |
| > %10 | -2.0 |
| Tramer bilinmiyor | -0.5 |
| Yıllık km 25–35 bin | -0.8 |
| Yıllık km 35–45 bin | -1.8 |
| Yıllık km < 4.000 ve araç ≥ 5 yaş | -1.0 + `km_degisimi_suphesi` uyarısı |
| Her olumsuz sinyal | -0.7 |
| Her belirsiz ifade | -0.3 |
| Her olumlu sinyal (max +1.0) | +0.4 |
| `sapma` -%5 ile -%15 arası | +0.5 |
| `sapma` < -%20 | 0 puan + "neden bu kadar ucuz?" uyarısı |
| Bilinen kronik arıza (models_kb.yaml) | -0.5 + kontrol maddesi |

Yıllık km = km / max(araç yaşı (ay/12), 1).

**Etiket:**
- 🔴 ALINMAZ: herhangi bir hard fail veya skor < 5.5
- 🟢 ALINIR: skor ≥ 7.5 VE sapma ≤ -%5 (plan matrisi: piyasadan en az %5 uygun; medyanda = 🟡) VE `sase_direk_podye_islem != "var"` VE `veri_tamlik ≥ 0.6` VE emsal sayısı ≥ 5 (tüm eşikler rules.yaml `etiket` bölümünde)
- 🟡 DÜŞÜNÜLEBİLİR: geri kalan her şey

`veri_tamlik`: yapılandırılmış alanların, parça diyagramının, tramer bilgisinin ve emsal sayısının dolu olma oranı (ağırlıklı).

### 4.4 Model bilgi tabanı — `config/models_kb.yaml`
```yaml
- marka: Renault
  model: Megane
  yillar: [2016, 2020]
  kronik:
    - etiket: "EDC şanzıman"
      kontrol: "Kalkışta silkeleme, düşük viteste vuruntu; test sürüşünde kontrol et"
```
Kullanıcı tarafından doldurulur; LLM ile öneri üretilebilir ama otomatik eklenmez.

### 4.5 Teklif hesaplayıcı — `analysis/offer.py`
```
baz = min(ilan_fiyati, medyan)
indirim = Σ(boyalı×%0.8, lokal×%0.4, değişen×%2.0, tramer_orani×0.5, yüksek_km_payi)
hedef = baz × (1 - indirim) × (1 - pazarlik_payi)   # pazarlik_payi varsayılan %3
taban = medyan × 0.85
tavsiye_teklif = round_to_5000(max(hedef, taban))
```
- 🔴 ilanlar için teklif üretilmez.
- Rapor iki değer verir: açılış teklifi ve üst sınır (`min(ilan, medyan × (1 - indirim))`).

## 5. Raporlama (Faz 3) — `report/card.py`
Karne formatı (Telegram ve Markdown aynı içerik):
```
🟢 ALINIR — ekspertize götürmeye değer
2018 Renault Megane 1.5 dCi Touch EDC · 98.000 km · Bursa/Nilüfer
Fiyat: 845.000 TL | Piyasa ilan medyanı: 940.000 TL (n=23) | -%10
Güven: 8.4/10 · Veri tamlığı: %80
✅ Tavan ve kaputlar orijinal · İlk sahibinden (beyan) · Servis bakımlı (beyan)
⚠️ Sağ arka çamurluk değişen · 18.000 TL tramer (açıklamadan)
💬 Teklif: 810.000 TL ile aç, 830.000 TL üst sınır
🔍 Ekspertizde mutlaka bakılacak: şase uçları, podyeler, direkler, airbag modülü, EDC test sürüşü
🔗 ilan linki
```
- "(beyan)" ekiyle satıcı iddiaları doğrulanmış bilgiden ayrılır.
- Her rapora ekspertiz kontrol listesi eklenir; şase/direk/podye/airbag ilan verisinden asla "doğrulandı" sayılmaz.

## 6. Çalışma modları (Faz 4)

### 6.1 Anlık arama
1. Kriterlerden URL üret → ilk N liste sayfası (varsayılan 3).
2. Liste düzeyinde ön eleme (bütçe, yıllık km, sapma) → yalnızca geçenlerin detayı çekilir (istek tasarrufu).
3. Detay → parse → LLM → piyasa → kural → rapor.
4. Çıktı: 🟢'ler skor sırasına göre, ardından en iyi 3 🟡. 🔴'ler yalnızca özet sayı olarak.

### 6.2 Radar
- `watches` tablosu: kriter, aralık (varsayılan 30 dk, minimum 15 dk), aktif saatler (örn. 08:00–23:00), sessiz mod.
- Her turda yalnızca tarihe göre sıralı ilk liste sayfası çekilir.
- `diff.py`: yeni ilan, fiyat düşüşü (≥ %3), yeniden yayınlanmış ilan (aynı başlık+km+yıl, farklı ilan no) tespiti.
- Bildirim: yalnızca 🟢, ve fiyat düşüşü sonrası 🟡 → 🟢 geçişleri. Günde bir "radar özeti" mesajı.
- Aynı ilan için tekrar bildirim gönderilmez (`notifications` tablosu).

## 7. Depolama şeması
`listings`, `listing_snapshots` (fiyat geçmişi), `parts`, `findings`, `verdicts`, `market_cache`, `watches`, `notifications`, `fetch_log` (rate limit + blok geçmişi).

## 8. Gözlemlenebilirlik
- Yapılandırılmış log (JSON), her ilan için karar izi: hangi kural kaç puan düşürdü.
- `arac explain <ilan_no>`: kararın tam dökümünü basar.
- Haftalık geri bildirim: kullanıcı Telegram'da 👍/👎 verir, `feedback` tablosuna yazılır; eşik ayarı için kullanılır.
