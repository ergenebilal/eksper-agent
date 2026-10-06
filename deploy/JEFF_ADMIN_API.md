# CyberOto yönetici API'si — Jeff için

Yönetim sayfasının (`/yonetim`) yaptığı her şey JSON olarak. **Yalnız Hermes sunucusunun içinden** çalışır:
adres `http://127.0.0.1:8991/admin-api/v1`, dışarıdan (nginx üzerinden) erişilemez. Her değiştirici işlem işlem
kaydına (`/islem-kaydi`) "jeff-api" olarak yazılır. İlan verisi yoktur; yalnız hesaplar, haklar, sayaçlar, geri bildirim.

**Anahtar:** `/home/hermes/.config/cyberoto/admin_api_token` (yalnız `hermes` kullanıcısı okur). Sunucudaki
`/opt/otoxray/.env` içindeki `ADMIN_API_TOKEN` ile aynıdır. Anahtarı mesajlara, loglara, Telegram'a yazma.

```bash
T=$(cat ~/.config/cyberoto/admin_api_token)
curl -s -H "Authorization: Bearer $T" http://127.0.0.1:8991/admin-api/v1/ozet
```

## Okuma
| İstek | Ne döner |
|---|---|
| `GET /saglik` | SMTP / LLM yapılandırılmış mı, genel adres |
| `GET /ozet` | Üye sayıları (durum), bugünkü / aylık analiz, geri bildirim, kalibrasyon özeti |
| `GET /uyeler` | Tüm üyeler: e-posta, ad, durum, günlük/aylık hak, bitiş, bugün/bu ay kullanım, cihaz sayısı, erişim sorunu |
| `GET /uyeler/{id ya da e-posta}` | Tek üye + son 50 geri bildirimi |
| `GET /geri-bildirim?limit=100` | Son geri bildirimler (oy, ekspertiz sonucu, not) |
| `GET /kalibrasyon` | Etiket × gerçek sonuç tablosu, yanlış yeşil ve kaçan aday listeleri |
| `GET /davetler` | Davet e-postası gönderim kayıtları |
| `GET /islem-kaydi?limit=100` | Bu API ile yapılan değişiklikler |

## Değiştirme (hepsi kayda geçer)
| İstek | Gövde (JSON) | Not |
|---|---|---|
| `POST /uyeler` | `{"email", "ad"?, "gunluk_kota"?, "aylik_kota"?, "bitis"? (YYYY-AA-GG), "rozet"?, "notu"?, "davet": true}` | Üye ekler; `davet: true` ise davet e-postası gider. Kayıtlıysa 409 |
| `PATCH /uyeler/{ref}` | Yalnız değişecek alanlar: `gunluk_kota`, `aylik_kota`, `bitis`, `rozet`, `ad`, `notu` | Haklar |
| `POST /uyeler/{ref}/durum` | `{"durum": "aktif" \| "durduruldu" \| "iptal"}` | `iptal` cihaz anahtarlarını da kalıcı kapatır |
| `POST /uyeler/{ref}/cihazlari-kapat` | — | Tüm cihazlardan çıkış (üye yeniden kodla girer) |
| `POST /uyeler/{ref}/davet` | — | Davet e-postasını yeniden gönderir |

Hata kodları: `401` anahtar yanlış, `404` üye yok ya da istek sunucu dışından geldi, `409` e-posta kayıtlı,
`422` geçersiz değer. Kullanıcıyı etkileyen işlemlerden (iptal, cihazları kapatma, toplu hak değişikliği) önce
Bilal'e sor.
