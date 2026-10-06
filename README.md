# Araç Eksper Ajanı

Sahibinden ilanlarını toplayıp 🟢 ALINIR / 🟡 DÜŞÜNÜLEBİLİR / 🔴 ALINMAZ karnesi üretir.
🟢 = **"ekspertize götürmeye değer"**, "al" değil: şase/direk/podye/airbag ilandan doğrulanamaz.

## Kurulum
```
uv sync
cp .env.example .env      # LLM havuzu, Telegram vb. doldur
uv run arac db init
uv run playwright install chromium
```

## Komutlar
| Komut | Ne yapar |
|---|---|
| `arac search --marka Renault --model Megane --max-butce 900000 --min-yil 2018 [--json]` | Anlık arama |
| `arac report <ilan_no> [--json]` / `arac explain <ilan_no>` | Kayıtlı karne / puan dökümü |
| `arac watch add --name megane --marka Renault --model Megane --max-butce 900000` | Radar ekle |
| `arac watch run [--once] [--json]` | Radarı çalıştır (internal: sürekli, `--once`/external: tek tur) |
| `arac watch resume` | Engel sonrası otomatik duraklatmayı kaldır |
| `arac status [--json]` | Son BAŞARILI çekim, engel durumu, saatlik kullanım, radar son turları |
| `arac events --since N --json` | Bildirim olayları (NOTIFY_MODE=jeff) |
| `arac map add Renault Megane <sahibinden-arama-url>` | Kategori slug'ı ekle |
| `arac import-html <dosya\|klasör>` | Elle kaydedilmiş sayfaları içe aktar (engel durumunda yedek yol) |
| `arac panel serve` | Salt okunur yönetim paneli (PANEL_TOKEN zorunlu, varsayılan 127.0.0.1:8990) |
| `arac feedback <ilan_no> pos\|neg` / `arac telegram poll` | Geri bildirim |
| `arac eval [--second-pass hard] [--limit N] [--json]` | Açıklama röntgenini `tests/data/aciklamalar.jsonl` ile ölçer (gerçek LLM); recall < %90 → çıkış 1 |

Çıkış kodları: `0` başarılı · `1` hata · `2` BLOCKED (doğrulama sayfası) · `3` geçersiz girdi.
`--json` modunda stdout yalnızca JSON'dur, loglar stderr'e gider.

## Toplama kuralları
Düşük hacim (sayfa başı 8–20 sn, saatte en fazla `MAX_PAGES_PER_HOUR`), kendi tarayıcı profilin, ev internetin.
Doğrulama sayfası çıkarsa sistem durur (backoff 30 dk → 2 sa → 6 sa), haber verir; **aşmaya çalışmaz**.
Ardışık 3 engelde radarlar duraklar. Proxy / fingerprint sahteciliği / CAPTCHA çözümü yoktur.

## Doğrulanmamış kısımlar
`parser/selectors.py`, `collector/url_builder.py` parametreleri ve `BLOCK_MARKERS` **gerçek sahibinden HTML'iyle doğrulanmadı**.
Gerçek sayfaları `tests/fixtures/real/` altına koyunca selector'lar yalnızca oradan çıkarılmalıdır.
`config/models_kb.yaml` içeriğini sen doldurursun.
