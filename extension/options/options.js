const $ = (id) => document.getElementById(id);
const DEFAULTS = { apiBase: 'http://127.0.0.1:8990', token: '', maxButce: null, autoAnalyze: true, autoBatch: true };

function say(text, kind) { const m = $('msg'); m.textContent = text; m.className = kind || ''; }

async function load() {
  const s = { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
  $('apiBase').value = s.apiBase;
  $('token').value = s.token;
  $('maxButce').value = s.maxButce || '';
  $('autoAnalyze').checked = !!s.autoAnalyze;
  $('autoBatch').checked = !!s.autoBatch;
}

function isLocal(host) { return /^(127\.|localhost$)/.test(host); }

async function save() {
  let origin;
  try { origin = new URL($('apiBase').value.trim()).origin; } catch (_) { say('Sunucu adresi geçersiz.', 'err'); return false; }
  const u = new URL(origin);
  // Yerel adresler manifestte izinli; başka bir kök için YALNIZ o kök için izin istenir (kullanıcı hareketiyle)
  if (!isLocal(u.hostname)) {
    const ok = await chrome.permissions.request({ origins: [origin + '/*'] });
    if (!ok) { say('Bu sunucuya erişim izni verilmedi.', 'err'); return false; }
  }
  await chrome.storage.local.set({
    apiBase: origin, token: $('token').value.trim(), maxButce: Number($('maxButce').value) || null,
    autoAnalyze: $('autoAnalyze').checked, autoBatch: $('autoBatch').checked
  });
  say('Kaydedildi.', 'ok');
  return true;
}

$('f').addEventListener('submit', (e) => { e.preventDefault(); save(); });
$('test').addEventListener('click', async () => {
  if (!(await save())) return;
  say('Test ediliyor…');
  const r = await chrome.runtime.sendMessage({ type: 'ping' });
  say(r && r.ok ? '✓ Bağlantı ve jeton doğru.' : (r && r.message) || 'Başarısız.', r && r.ok ? 'ok' : 'err');
});
load();
