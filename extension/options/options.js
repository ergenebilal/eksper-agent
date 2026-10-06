/* CyberOto ayarlar: e-posta koduyla giriş (anahtar sayfaya hiç verilmez, service worker saklar), tercihler, gelişmiş. */
const $ = (id) => document.getElementById(id);
const DEFAULTS = { apiBase: 'https://cyberoto.cybergene.co', token: '', email: '', maxButce: null, autoAnalyze: false, autoBatch: true };

function say(id, text, kind) { const m = $(id); m.textContent = text; m.className = 'msg' + (kind ? ' ' + kind : ''); }
const send = (msg) => chrome.runtime.sendMessage(msg);

async function load() {
  const s = { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
  $('apiBase').value = s.apiBase;
  $('token').value = s.email ? '' : s.token;          // e-postayla alınan cihaz anahtarı gösterilmez
  $('maxButce').value = s.maxButce || '';
  $('autoAnalyze').checked = !!s.autoAnalyze;
  $('autoBatch').checked = !!s.autoBatch;
  await showAccount(s);
}

function rightsList(k) {
  const dl = $('rights'); dl.replaceChildren();
  const add = (t, v) => { const d = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd');
    dt.textContent = t; dd.textContent = v; d.append(dt, dd); dl.append(d); };
  if (!k) return;
  add('Bugün kalan', `${Math.max(k.limit - k.kullanilan, 0)} / ${k.limit}`);
  if (k.aylik) add('Bu ay kalan', `${Math.max(k.aylik.limit - k.aylik.kullanilan, 0)} / ${k.aylik.limit}`);
  add('Erişim', k.bitis ? `${new Date(k.bitis + 'T00:00:00').toLocaleDateString('tr-TR')} tarihine kadar` : 'Süre sınırı yok');
}

async function showAccount(s) {
  const signed = !!(s.token && s.email);
  $('signed-in').hidden = !signed;
  $('signed-out').hidden = signed;
  if (!signed) return;
  $('who').textContent = s.email;
  const r = await send({ type: 'ping' });
  if (r && r.ok) rightsList(r.data.kota);
  else say('auth-msg', (r && r.message) || 'Sunucuya ulaşılamadı.', 'err');
}

$('email-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('send-code').disabled = true;
  say('auth-msg', 'Gönderiliyor…');
  const r = await send({ type: 'auth:kod', email: $('email').value.trim() });
  $('send-code').disabled = false;
  if (!r || !r.ok) { say('auth-msg', (r && r.message) || 'Kod gönderilemedi.', 'err'); return; }
  say('auth-msg', r.data.mesaj, 'ok');
  $('code-form').hidden = false;
  $('code').focus();
});

$('code-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('login').disabled = true;
  const r = await send({ type: 'auth:giris', email: $('email').value.trim(), kod: $('code').value.trim() });
  $('login').disabled = false;
  if (!r || !r.ok) { say('auth-msg', (r && r.message) || 'Giriş yapılamadı.', 'err'); return; }
  $('code').value = ''; $('code-form').hidden = true;
  say('auth-msg', 'Giriş yapıldı. Artık bir ilan açabilirsiniz.', 'ok');
  load();
});

$('logout').addEventListener('click', async () => {
  await send({ type: 'auth:cikis' });
  say('auth-msg', 'Çıkış yapıldı.', 'ok');
  load();
});

function isLocal(host) { return /^(127\.|localhost$)/.test(host); }

async function save() {
  let origin;
  try { origin = new URL($('apiBase').value.trim()).origin; } catch (_) { say('msg', 'Sunucu adresi geçersiz.', 'err'); return false; }
  const u = new URL(origin);
  // Manifestte izinli olmayan bir kök için YALNIZ o kök için izin istenir (kullanıcı hareketiyle)
  if (!isLocal(u.hostname)) {
    const ok = await chrome.permissions.request({ origins: [origin + '/*'] });
    if (!ok) { say('msg', 'Bu sunucuya erişim izni verilmedi.', 'err'); return false; }
  }
  const owner = $('token').value.trim();
  const patch = { apiBase: origin, maxButce: Number($('maxButce').value) || null,
                  autoAnalyze: $('autoAnalyze').checked, autoBatch: $('autoBatch').checked };
  if (owner) Object.assign(patch, { token: owner, email: '' });     // sahip anahtarı e-posta oturumunun yerine geçer
  await chrome.storage.local.set(patch);
  say('msg', 'Kaydedildi.', 'ok');
  return true;
}

$('f').addEventListener('submit', (e) => { e.preventDefault(); save(); });
$('test').addEventListener('click', async () => {
  if (!(await save())) return;
  say('msg', 'Test ediliyor…');
  const r = await send({ type: 'ping' });
  const k = r && r.ok && r.data && r.data.kota;
  say('msg', r && r.ok ? 'Bağlantı çalışıyor.' + (k ? ` Bugünkü hakkınız: ${k.limit - k.kullanilan}/${k.limit}` : '')
                       : (r && r.message) || 'Başarısız.', r && r.ok ? 'ok' : 'err');
});
$('wipe').addEventListener('click', async () => {
  const r = await send({ type: 'clearLocalData' });
  say('msg', r && r.ok ? 'Yerel emsal ve sonuç verileri silindi.' : 'Silinemedi.', r && r.ok ? 'ok' : 'err');
});
$('legal').textContent = globalThis.OTOXRAY_DISCLAIMER;
load();
