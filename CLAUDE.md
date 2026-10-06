# CLAUDE.md — Araç Eksper Ajanı

Bu dosya Claude Code için proje bağlamıdır. Her oturumda önce bunu, sonra `SPEC.md` ve `TASKS.md` dosyalarını oku.

## Proje özeti
Kişisel kullanım için ikinci el araç ön-eleme ajanı. Sahibinden.com ilanlarını toplar, yapılandırılmış veriye çevirir, kural motoru + LLM açıklama analizi ile değerlendirir ve 🟢 / 🟡 / 🔴 etiketli bir karne üretir. İki mod: Anlık Arama ve Radar (periyodik takip + Telegram bildirimi).

Ajanın ürettiği 🟢 etiketi "satın al" değil, "fiziksel ekspertize götürmeye değer" anlamındadır. Bu ifade raporlarda her zaman yer alır.

## Teknoloji
- Python 3.12, `uv` ile paket yönetimi
- Playwright (Chromium, **headed**, persistent context)
- Pydantic v2 (tüm veri modelleri)
- SQLite + SQLAlchemy 2.0 (ileride Postgres'e geçilebilir şekilde)
- LLM: sağlayıcı-bağımsız `LLMClient` arayüzü (Anthropic / OpenAI / DeepSeek adaptörleri)
- Bildirim: Telegram Bot API (`python-telegram-bot` veya düz HTTP)
- Zamanlayıcı: APScheduler (alternatif: n8n'den HTTP tetik)
- CLI: Typer
- Test: pytest, kayıtlı HTML fixture'ları ile

## Klasör yapısı
```
arac_eksper/
  config/            # settings.py (pydantic-settings), rules.yaml, models_kb.yaml
  collector/         # url_builder.py, base.py, playwright_collector.py, manual_import.py
  parser/            # list_parser.py, detail_parser.py, damage_parser.py
  analysis/          # description_llm.py, market.py, rules_engine.py, scoring.py, offer.py
  report/            # card.py, telegram.py, markdown.py
  watcher/           # scheduler.py, diff.py
  storage/           # db.py, models.py, repo.py
  llm/               # client.py, anthropic.py, openai.py, deepseek.py
  cli.py
tests/
  fixtures/          # gerçek sayfalardan kaydedilmiş HTML'ler (kişisel veriler maskelenmiş)
```

## Kurallar (pazarlıksız)
1. **Toplama nazik ve düşük hacimli olur.** Sayfa başına 8–20 sn rastgele bekleme, saatte en fazla `MAX_PAGES_PER_HOUR` (varsayılan 40) sayfa. Limit kod seviyesinde zorunlu, config ile kapatılamaz.
2. **Bot doğrulaması / CAPTCHA çıkarsa çözmeye çalışılmaz.** Toplayıcı durur, durum `BLOCKED` olarak kaydedilir, Telegram'a "manuel müdahale gerekli" bildirimi gider, backoff ile bekler.
3. Fingerprint sahteciliği, proxy rotasyonu, CAPTCHA çözücü servisler eklenmez.
4. Toplanan veri yalnızca yerel DB'de tutulur, üçüncü taraflarla paylaşılmaz. Satıcı telefon numarası ve adı saklanmaz.
5. Selector'lar tek bir dosyada (`parser/selectors.py`) toplanır; DOM değişince yalnızca orası güncellenir. Selector'lar fixture'lardan çıkarılır, tahmin edilmez.
6. Her parser fonksiyonu fixture tabanlı testle gelir. Test yoksa iş bitmiş sayılmaz.
7. Kural eşikleri koda gömülmez, `config/rules.yaml`'dan okunur.
8. LLM çıktısı her zaman JSON şemasıyla doğrulanır; her bulgu açıklamadan alıntılanan kanıt cümlesi içerir. Kanıtsız bulgu atılır.
9. Bilinmeyen veri "iyi" sayılmaz. Belirtilmemiş parça = `UNKNOWN`, puanlamada nötr değil hafif negatif.

## Çalıştırma
```
uv run arac search --marka "Renault" --model "Megane" --max-butce 900000 --min-yil 2016
uv run arac watch add --name megane-radar --from-search last
uv run arac watch run
uv run arac report <ilan_no>
```
