# otoXray — davetli kullanım için barındırma

## Canlı kurulum: Hermes (CyberGene) — 6 Ekim 2026
| | |
|---|---|
| Adres | `https://otoxray.cybergene.co` (DNS kaydı + sertifika: aşağıdaki "Kalan adımlar") |
| Sunucu | `hermes` (genel IP 13.140.183.88, Tailscale 100.80.122.74), Ubuntu 24.04 |
| Uygulama | `/opt/otoxray`, sistem kullanıcısı `otoxray` (Jeff dosyalarını okuyamaz), systemd `otoxray.service`, 127.0.0.1:8991 |
| Ters vekil | Mevcut **nginx** (Caddy değil): `/etc/nginx/sites-available/otoxray.cybergene.co` = [nginx-otoxray.conf](nginx-otoxray.conf) |
| Gizli ayarlar | `/opt/otoxray/.env` (600, yalnız `otoxray`); sahip anahtarı orada üretildi |
| Hesaplar | `/opt/otoxray/data/xray_accounts.db` |
| Güncelleme | `bash deploy/redeploy.sh` (son commit'i gönderir, `.env` ve `data/` korunur) |

Kalan adımlar (sende):
1. **DNS:** `otoxray.cybergene.co` için `A` kaydı → `13.140.183.88`.
2. **HTTPS:** DNS yayılınca sunucuda `sudo certbot --nginx -d otoxray.cybergene.co`.
3. **LLM ayarları:** `sudo -u otoxray nano /opt/otoxray/.env` ile yerel `.env` dosyandaki `LLM_BASE_URL`,
   `LLM_API_KEY`, `LLM_MODEL_FAST` ve `LLM_MODEL_STRONG` satırlarını ekle, sonra `sudo systemctl restart otoxray`.
4. **Sahip anahtarın** (kendi eklentin için): `sudo grep EXTENSION_TOKEN /opt/otoxray/.env`.

### Davetli yönetimi (e-postaya bağlı)
- **Web:** `https://otoxray.cybergene.co/yonetim`. `ADMIN_EMAILS` listesindeki adrese gelen kodla girilir.
  Burada üye eklenir, günlük/aylık hak, bitiş tarihi ve rozet izni belirlenir, üye durdurulur/iptal edilir,
  cihaz oturumları kapatılır, davet yeniden gönderilir ve geri bildirimler görülür.
- **Davetli:** davet e-postasındaki bağlantıdan eklentiyi kurar, ayarlarda e-postasını yazar, gelen 6 haneli kodu girer.
  Anahtar kopyalamak gerekmez; her cihaz kendi anahtarını alır.
- **Gerekenler (`.env`):** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ADMIN_EMAILS`, `STORE_URL`
  (bkz. [env.production.example](env.production.example)). SMTP yoksa kod gönderilemez ve yönetim sayfası bunu açıkça gösterir.
- **Komutla da yapılabilir:**
  `cd /opt/otoxray && sudo -u otoxray .venv/bin/arac xray user add ayse@ornek.com --gunluk 30 --bitis 2026-12-31 --davet`.
  Diğer komutlar: `user list|set|pause|resume|revoke|logout`, `xray feedback`.

---

Amaç: davetli kullanıcılar **yalnızca eklentiyi** alır. Analiz beyni (prompt, jargon sözlüğü, kurallar, bilgi tabanı,
ölçüm seti) **yalnızca bu sunucuda** durur. Kullanıcıya sunucu kodu, `.env` ya da `arac xray serve` verilmez.

```
Davetli tarayıcısı (eklenti) ──HTTPS + kişisel anahtar──► Caddy (443) ──► arac xray serve (127.0.0.1:8991) ──► LLM
```

## 1. Sunucu (küçük bir VPS yeter: 1 vCPU / 1 GB)
Linux tarafında çalıştırılacak komutlar:

```bash
sudo useradd --system --create-home otoxray
sudo mkdir -p /opt/otoxray && sudo chown otoxray: /opt/otoxray
sudo -u otoxray git clone <özel-depo> /opt/otoxray      # depo ÖZEL kalmalı
cd /opt/otoxray && sudo -u otoxray ~otoxray/.local/bin/uv sync --no-dev
sudo -u otoxray cp deploy/env.production.example .env   # değerleri doldur
sudo cp deploy/otoxray.service /etc/systemd/system/ && sudo systemctl enable --now otoxray
```

Caddy'yi kurun, `deploy/Caddyfile` içindeki `ALAN_ADINIZ` değerini değiştirip `/etc/caddy/Caddyfile` olarak koyun,
ardından `sudo systemctl reload caddy` çalıştırın. Alan adının DNS A kaydı sunucunun IP adresini göstermeli.

Kontrol: `curl https://ALAN_ADINIZ/healthz` → `{"ok":true}`. Panel (8990) ve toplayıcı bu sunucuda **çalıştırılmaz**.

## 2. Davetli ekleme / çıkarma
```bash
cd /opt/otoxray
.venv/bin/arac xray user add "Ayşe" --kota 30   # anahtar BİR KEZ gösterilir; kişiye güvenli kanaldan ilet
.venv/bin/arac xray user list                   # bugünkü kullanım, toplam, geri bildirim sayısı
.venv/bin/arac xray user revoke 3               # sızan ya da artık kullanılmayan anahtar
.venv/bin/arac xray user quota 3 50
.venv/bin/arac xray feedback                    # gelen 👍/👎, ekspertiz sonuçları, notlar
```

Hesap dosyası: `data/xray_accounts.db`. İçinde anahtarın özeti (anahtarın kendisi değil), günlük sayaçlar ve
geri bildirimler var. Bu dosyayı düzenli yedekleyin. İlan açıklaması bu dosyada **yoktur**.

## 3. Eklentiyi davetliye verme
- Chrome Web Store'a **"Liste dışı" (Unlisted)** olarak yükleyin: aramada çıkmaz, yalnızca bağlantıyı alan kurar.
  Geliştirici hesabı bir kerelik ücretlidir.
- Davetli kurulumdan sonra **Ayarlar** sayfasında şunları girer:
  - Sunucu adresi: `https://ALAN_ADINIZ`. Chrome bu adres için izin ister.
  - Erişim anahtarı: `oxr_…`
- **Bağlantıyı test et** düğmesi bugünkü kalan hakkı gösterir.

## 4. Kopyalanmaya karşı ne yapıldı, ne yapılamaz
| Önlem | Durum |
|---|---|
| Analiz beyni yalnız sunucuda | ✓ Eklentide prompt, kural ya da sözlük yok |
| Kişi başı, iptal edilebilir anahtar | ✓ `arac xray user revoke` |
| Kişi başı günlük kota (analiz, rozet, ön hesap) | ✓ Toplu sorgu ile çıktı biriktirmeyi zorlaştırır |
| Kural ağırlıkları (puan dökümü) davetliye gönderilmez | ✓ `trace` yalnız sahip anahtarına döner |
| API belgeleri kapalı | ✓ `/docs` ve `/openapi.json` yok |
| Eklenti JavaScript'i | ✗ Gizlenemez; değer zaten sunucuda olduğundan kopyası tek başına işe yaramaz |
| Çıktıdan tersine mühendislik | Kısmen: kota ve iptal yavaşlatır. Hukuki koruma için kullanım koşulları ve marka tescili gerekir |
