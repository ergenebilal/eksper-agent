#!/usr/bin/env bash
# Alan adı geçişi: otoxray.cybergene.co → cyberoto.cybergene.co (2026-10-07, kullanıcı kararı).
# Önkoşul: DNS'te `cyberoto.cybergene.co` A kaydı → 13.140.183.88 (betik kontrol eder, yoksa hiçbir şeye dokunmadan durur).
# Yapılanlar (sunucuda, hepsi yedekli ve tekrar çalıştırılabilir):
#   1. Yeni nginx sitesi (deploy/nginx-cyberoto.conf) + Let's Encrypt sertifikası (certbot --nginx).
#   2. .env: PUBLIC_URL yeni adres (e-posta logoları/bağlantılar). PANEL_ALLOWED_HOSTS iki adı da içerir.
#   3. Eski site → geçiş yapılandırması (deploy/nginx-otoxray-gecis.conf): API ve sağlık eski adreste de çalışır,
#      tarayıcı istekleri (yönetim sayfası) yeni adrese 301.
#   4. Servis yeniden başlar; yeni adreste /healthz ve eski adreste API kontrol edilir.
# Oturumlar: eklenti cihaz anahtarları alan adından bağımsızdır (yeniden giriş gerekmez; 0.2.0 eklenti yeni adrese
# kendisi geçer). Yönetim çerezi alan adına bağlıdır: yöneticiler yeni adreste bir kez e-posta koduyla girer.
# Kullanım: bash deploy/alan-adi-gecisi.sh
set -euo pipefail
HOST="${OTOXRAY_HOST:-hermes@100.80.122.74}"
KEY="${OTOXRAY_KEY:-$HOME/.ssh/bilal_ssh_key}"
YENI=cyberoto.cybergene.co
ESKI=otoxray.cybergene.co
IP=13.140.183.88
cd "$(git rev-parse --show-toplevel)"

scp -q -i "$KEY" deploy/nginx-cyberoto.conf "$HOST:/tmp/nginx-cyberoto.conf"
scp -q -i "$KEY" deploy/nginx-otoxray-gecis.conf "$HOST:/tmp/nginx-otoxray-gecis.conf"
ssh -i "$KEY" "$HOST" "set -euo pipefail
dns=\$(getent ahostsv4 $YENI | awk '{print \$1}' | head -1 || true)
if [ \"\$dns\" != '$IP' ]; then
  echo 'DNS hazır değil: $YENI → '\"\${dns:-yok}\"' (beklenen $IP). Hiçbir şey değiştirilmedi.' >&2; exit 2
fi
ts=\$(date +%Y%m%d%H%M%S)
sudo cp -p /etc/nginx/sites-available/$ESKI /root/otoxray-nginx.bak.\$ts
sudo cp -p /opt/otoxray/.env /root/otoxray-env.bak.\$ts

# 1) yeni site + sertifika
if [ ! -f /etc/nginx/sites-available/$YENI ]; then
  sudo install -m 644 /tmp/nginx-cyberoto.conf /etc/nginx/sites-available/$YENI
  sudo ln -sf /etc/nginx/sites-available/$YENI /etc/nginx/sites-enabled/$YENI
  sudo nginx -t && sudo systemctl reload nginx
fi
if ! sudo grep -q 'ssl_certificate' /etc/nginx/sites-available/$YENI; then
  sudo certbot --nginx -d $YENI --non-interactive --agree-tos --redirect --keep-until-expiring
fi

# 2) .env
sudo sed -i 's|^PUBLIC_URL=.*|PUBLIC_URL=https://$YENI|' /opt/otoxray/.env
sudo grep -q '^PUBLIC_URL=' /opt/otoxray/.env || echo 'PUBLIC_URL=https://$YENI' | sudo tee -a /opt/otoxray/.env >/dev/null
sudo grep -q '\"$YENI\"' /opt/otoxray/.env || { echo 'PANEL_ALLOWED_HOSTS yeni adı içermiyor' >&2; exit 3; }

# 3) eski site → geçiş
sudo install -m 644 /tmp/nginx-otoxray-gecis.conf /etc/nginx/sites-available/$ESKI
sudo nginx -t && sudo systemctl reload nginx
rm -f /tmp/nginx-cyberoto.conf /tmp/nginx-otoxray-gecis.conf

# 4) servis + kontroller
sudo systemctl restart otoxray
for i in \$(seq 30); do curl -sf -m 3 https://$YENI/healthz >/dev/null && break; sleep 1; done
curl -sf -m 5 https://$YENI/healthz && echo
curl -sf -m 5 https://$ESKI/healthz >/dev/null && echo 'eski adres: API/sağlık çalışıyor'
test \"\$(curl -s -o /dev/null -w '%{http_code}' https://$ESKI/yonetim)\" = 301 && echo 'eski adres: yönetim sayfası yeni adrese yönleniyor'
"
echo "Geçiş tamam: https://$YENI"
