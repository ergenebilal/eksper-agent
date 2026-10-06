# TASKS.md — Uygulama Sırası

Her görev tek bir Claude Code oturumunda bitirilecek büyüklükte. Bir görev, kabul kriterleri ve testleri geçmeden sonrakine geçilmez.

## M0 — İskelet
- [ ] **T0.1** `uv` projesi, klasör yapısı, `pydantic-settings` ile `.env` okuma, Typer CLI iskeleti.
  Kabul: `uv run arac --help` çalışır, `pytest` boş da olsa yeşil.
- [ ] **T0.2** SQLAlchemy modelleri + Alembic migration (SPEC §7).
  Kabul: `arac db init` tabloları oluşturur, repo katmanı için CRUD testleri geçer.

## M1 — Parser (önce offline)
- [ ] **T1.1** Kullanıcı `tests/fixtures/` altına en az 3 liste ve 10 detay sayfası HTML'i koyar (elle kaydedilir). Kişisel veriler maskelenir.
- [ ] **T1.2** `parser/selectors.py` + `list_parser`. Kabul: fixture'lardaki tüm ilanlar doğru alanlarla parse edilir.
- [ ] **T1.3** `detail_parser` + `damage_parser`. Kabul: SPEC §3 kabul kriteri.
- [ ] **T1.4** `ManualImportCollector` + `arac import`. Kabul: klasördeki HTML'ler DB'ye `ListingDetail` olarak yazılır.

> Bu noktada sistem tarayıcı otomasyonu olmadan uçtan uca beslenebilir hale gelir.

## M2 — Analiz
- [ ] **T2.1** `llm/client.py` arayüzü + en az iki sağlayıcı adaptörü, JSON şema doğrulama, retry.
- [ ] **T2.2** `config/jargon.yaml` + `description_llm.py` + kanıt doğrulama + cache.
  Kabul: `tests/data/aciklamalar.jsonl` (30 etiketli örnek) üzerinde kırmızı bayrak recall ≥ %90.
- [ ] **T2.3** `market.py`. Kabul: sentetik veriyle medyan, IQR ve genişletme davranışı testleri.
- [ ] **T2.4** `rules.yaml` + `rules_engine.py` + `scoring.py`. Kabul: her hard fail ve her puan kuralı için ayrı birim testi; `arac explain` karar izini basar.
- [ ] **T2.5** `offer.py`. Kabul: 🔴'de teklif yok, taban kuralı çalışıyor, 5.000'e yuvarlama doğru.

## M3 — Rapor ve bildirim
- [ ] **T3.1** `report/card.py` Markdown çıktısı (SPEC §5 formatı birebir).
- [ ] **T3.2** Telegram gönderimi, 👍/👎 inline butonları, `feedback` tablosu.

## M4 — Canlı toplama
- [ ] **T4.1** `url_builder` + `category_map.yaml` + `arac map add`.
- [ ] **T4.2** `PlaywrightCollector`: persistent profil, rate limiter (DB kalıcı), engel tespiti, backoff, ham HTML saklama.
  Kabul: sahte sunucuya karşı entegrasyon testi — 403 ve doğrulama sayfası senaryolarında `BLOCKED` döner, Telegram uyarısı tetiklenir, limit aşımında istek atılmaz.
- [ ] **T4.3** `arac search`: SPEC §6.1 akışı, liste düzeyinde ön eleme.

## M5 — Radar
- [ ] **T5.1** `watches` CRUD komutları.
- [ ] **T5.2** `diff.py`: yeni ilan, fiyat düşüşü, yeniden yayın tespiti + testler.
- [ ] **T5.3** APScheduler ile `arac watch run`, aktif saatler, otomatik duraklatma, günlük özet.
- [ ] **T5.4** (Opsiyonel) n8n'den tetiklenebilmesi için küçük FastAPI uç noktası: `POST /watch/{id}/run`.

## M6 — Kalibrasyon
- [ ] **T6.1** İlk 2 haftanın 👍/👎 geri bildirimiyle eşik raporu: hangi kural en çok yanlış 🔴/🟢 üretti.
- [ ] **T6.2** `models_kb.yaml`'ı hedef modeller için doldur.
