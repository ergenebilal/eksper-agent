#!/usr/bin/env bash
# otoXray API'sini Hermes'e yeniden yayınlar: son COMMIT'i (çalışma ağacını değil) gönderir, bağımlılıkları eşitler,
# servisi yeniden başlatır ve sağlık kontrolü yapar. Sunucudaki .env ve data/ (hesaplar) korunur.
# Kullanım: bash deploy/redeploy.sh   (OTOXRAY_HOST / OTOXRAY_KEY ile değiştirilebilir)
set -euo pipefail
HOST="${OTOXRAY_HOST:-hermes@100.80.122.74}"
KEY="${OTOXRAY_KEY:-$HOME/.ssh/bilal_ssh_key}"
cd "$(git rev-parse --show-toplevel)"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Commit edilmemiş değişiklik var; önce commit et (yayınlanan şey son commit'tir)." >&2
  exit 1
fi
REV="$(git rev-parse --short HEAD)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive --format=tar.gz -o "$TMP/otoxray.tgz" HEAD
scp -q -i "$KEY" "$TMP/otoxray.tgz" "$HOST:/tmp/otoxray-$REV.tgz"
ssh -i "$KEY" "$HOST" "set -e
sudo tar -xzf /tmp/otoxray-$REV.tgz -C /opt/otoxray && rm /tmp/otoxray-$REV.tgz
echo $REV | sudo tee /opt/otoxray/DEPLOYED >/dev/null
sudo chown -R otoxray:otoxray /opt/otoxray
cd /opt/otoxray && sudo -u otoxray env HOME=/var/lib/otoxray UV_PYTHON_DOWNLOADS=never \
  /usr/local/bin/uv sync --frozen --no-dev --python /usr/bin/python3.12 -q
sudo systemctl restart otoxray
for i in \$(seq 30); do curl -sf -m 2 -H 'Host: 127.0.0.1' http://127.0.0.1:8991/healthz && exit 0; sleep 1; done
echo 'Servis 30 sn içinde sağlıklı yanıt vermedi: sudo journalctl -u otoxray -n 50' >&2; exit 1"
echo
echo "Yayında: $REV"
