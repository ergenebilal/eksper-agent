# otoXray — davetli kullanım için barındırma

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
