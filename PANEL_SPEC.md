# Panel Tasarım Planı

## Temel Kararlar
* **Yerel Öncelikli:** Panel, `arac`'ın çalıştığı evdeki makinede çalışır (Playwright ve ev IP'si orada). Varsayılan bind `127.0.0.1`, Bearer token zorunlu. Telefondan erişim için Tailscale (açık internete çıkarma).
* **Tek API, İki İstemci:** Panel ile Jeff aynı FastAPI'yi kullanır (Jeff master promptundaki A2 uç noktaları). Böylece Jeff için ayrıca HTTP katmanı yazılmaz.
* **Mobil Öncelikli:** Panele çoğunlukla telefondan bakarsın. Push bildirim Telegram'da kalır, panel durum ve karar yeridir.
* **Teknoloji:** FastAPI + Jinja2 + HTMX + Chart.js. Node build adımı yok, Antigravity ve Claude Code için hızlı ve bakımı kolay. İleride ihtiyaç olursa React'e geçilir, API aynı kalır.
* **Korumalar Aşılamaz:** Panel, korumaları aşamaz. Rate limiter, engel beklemesi ve tek toplama kilidi panelden kapatılamaz ya da gevşetilemez.

## Mimari
```
Tarayıcı/telefon ──HTMX──► FastAPI (127.0.0.1) ──► pipeline.py ──► collector (guard, lock)
Jeff ─────────HTTP────────►     │                      │
                                └──► SQLite ◄──────────┘   Telegram (bildirim)
```
Uzun işler (arama, radar turu) iş kuyruğuna girer: `POST /v1/search` → `202 {job_id}`, panel ilerlemeyi `GET /v1/jobs/{id}` ile okur. Aynı anda en fazla 1 toplama işi çalışır.

## Ekranlar
| Ekran | Gösterdiği | Eylemler |
| --- | --- | --- |
| **Genel Bakış** | Son başarılı çekim, engel durumu ve bitiş saati, saatlik sayfa kullanımı (x/40), radar durumları, son 24 saatte 🟢/🟡/🔴 sayısı, LLM bekleyen sayısı | Radar duraklat/başlat |
| **İlanlar** | Filtrelenebilir tablo: etiket, skor, fiyat, medyana sapma, km, il, tarih. Varsayılan sıralama: 🟢, sonra skor | Filtre, arama, CSV dışa aktar |
| **İlan Detayı** | Karne, puan dökümü (explain), parça diyagramı, açıklama metni (LLM alıntıları işaretli), fiyat geçmişi, teklif ve üst sınır, ekspertiz kontrol listesi, ilan linki | 👍/👎, "ekspertize gittim" notu, yeniden analiz |
| **Yeni Arama** | Kriter formu (marka, model, bütçe, yıl, km, vites, yakıt), canlı ilerleme | Başlat/iptal |
| **Radarlar** | Liste, aralık, aktif saatler, son 10 tur sonucu, bekleyen backlog | Ekle/düzenle/duraklat |
| **Kurallar** | `rules.yaml` ağırlık ve eşikleri form olarak, models_kb, jargon listesi | Kural editörü |
| **Piyasa** | Marka/model bazlı fiyat dağılımı, medyan trendi, emsal sayısı | Yok (salt okunur) |
| **Bildirimler** | Events listesi, iletildi/bekliyor, kanal modu | Telegram test mesajı, NOTIFY_MODE değiştir |
| **Sistem** | Fetch logları, engel zaman çizelgesi, LLM çağrıları, cache isabeti, hatalar | Log filtreleme |
| **Kalibrasyon** | 👍/👎'ye karşı etiketler, hangi kural en çok yanlış 🟢/🔴 üretti | Eşik önerilerini incele |
| **Araçlar** | Kategori haritası (URL yapıştır → slug), HTML içe aktar (sürükle-bırak) | Ekle, içe aktar |

## Genel Bakış Taslağı (Telefon)
```
┌──────────────────────────────┐
│ ● Toplama: ÇALIŞIYOR         │
│ Son başarılı çekim: 14:32    │
│ Sayfa kullanımı: 12/40       │
├──────────────────────────────┤
│ 🟢 3   🟡 9   🔴 41  (24 sa) │
│ ⏳ LLM bekleyen: 0           │
├──────────────────────────────┤
│ Radar megane   ● 14:30 ✓     │
│ Radar corolla  ⏸ duraklatıldı│
├──────────────────────────────┤
│ 🎯 Yeni 🟢: 2018 Megane 845k │
│    -%10 · 8.4/10  [Aç]       │
└──────────────────────────────┘
```
Engel varsa üstte kırmızı şerit: "Doğrulama sayfası çıktı. Manuel müdahale gerekli. Bekleme: 16:00'a kadar."

## Kural Editörü (En hassas ekran)
Ağırlıkları yalnızca sen değiştirirsin, bu yüzden:
* Değişiklik kaydetmeden önce simülasyon: "Son 200 kararda bu değerlerle kaç ilanın etiketi değişirdi?" (🟡→🟢: 4, 🟢→🟡: 1). Örnek ilanlar listelenir.
* Aralık doğrulaması (örn. alinir_max_sapma pozitif olamaz).
* Her kayıt `rule_versions` tablosuna yazılır, tek tıkla geri alınır.
* `rules.yaml` dosyası kaynak olarak kalır, panel yazarken yedek alır.

## Panelden Yapılamayacaklar
* Rate limiter'ı kapatma ya da limiti donanım sınırının üstüne çıkarma
* Engel beklemesi sırasında "şimdi dene"
* Proxy, fingerprint ya da CAPTCHA çözümü ayarı
* Satıcıya mesaj atma
* API anahtarlarını görme (maskeli gösterilir)

Tek istisna: doğrulama sayfasını sen kendi tarayıcında elle geçtikten sonra "Engeli temizle" butonu. Onay penceresi çıkar ve işlem loglanır. Tekrar engel gelirse zincir kaldığı yerden devam eder.

## Backend'e Eklenecekler
* **Tablolar:** `jobs`, `rule_versions`, `llm_calls` (model, süre, token, cache isabeti), `audit_log`, `listing_notes`
* **Uç noktalar:** `/v1/listings`, `/v1/listings/{no}`, `/v1/jobs`, `/v1/watches` (CRUD), `/v1/rules` (GET/PUT/simulate), `/v1/events`, `/v1/status`, `/v1/feedback`
* **Auth:** token, oturum çerezi, CSRF, rate limit

## Aşamalar
| Faz | İçerik | Risk |
| --- | --- | --- |
| **P0 – Salt okunur** | Genel Bakış, İlanlar, İlan Detayı, Bildirimler, Sistem | Düşük: hiçbir şeyi değiştirmez |
| **P1 – Kontrol** | Yeni Arama (iş kuyruğu), Radar CRUD, feedback, Araçlar | Orta: toplamayı tetikler, korumalar API katmanında |
| **P2 – Kurallar ve kalibrasyon** | Kural editörü + simülasyon + sürümleme, Kalibrasyon | Orta: karar mantığını etkiler |
| **P3 – Piyasa ve maliyet** | Fiyat grafikleri, LLM kota ekranı, Jeff entegrasyon token'ları | Düşük |
