/* MV3 service worker: ağa çıkan TEK katman. Durum bellekte tutulmaz (worker her an öldürülebilir):
 * ayarlar chrome.storage.local, sekme sonuçları chrome.storage.session ("r:<tabId>"). Dinleyiciler üst düzeyde kaydedilir.
 * Token yalnızca burada okunur; content script'e/sayfaya ASLA verilmez. Sahibinden'e HİÇBİR istek atılmaz. */
const DEFAULTS = { apiBase: 'http://127.0.0.1:8990', token: '', maxButce: null, autoAnalyze: true, autoBatch: true };
const TIMEOUT_MS = 120000;       // LLM çözümlemesi uzun sürebilir
const KEY = (tabId) => `r:${tabId}`;

async function getSettings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
}

function isLoopbackOrPrivate(host) {
  return /^(127\.|localhost$|\[::1\]$|10\.|192\.168\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|.*\.ts\.net$)/.test(host);
}

/** Yalnızca origin kabul edilir (yol/sorgu yok); http sadece yerel/özel ağda. */
function validBase(base) {
  try {
    const u = new URL(base);
    if (u.pathname !== '/' || u.search || u.hash || u.username) return null;
    if (u.protocol === 'https:' || (u.protocol === 'http:' && isLoopbackOrPrivate(u.hostname))) return u.origin;
  } catch (_) { /* geçersiz */ }
  return null;
}

async function api(path, { method = 'POST', body } = {}) {
  const s = await getSettings();
  if (!s.token) return { ok: false, code: 'no_token', message: 'Ayarlardan erişim jetonunu girin.' };
  const base = validBase(s.apiBase);
  if (!base) return { ok: false, code: 'bad_base', message: 'Sunucu adresi geçersiz.' };
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(base + path, {
      method, signal: ctl.signal, cache: 'no-store', credentials: 'omit',
      headers: { Authorization: 'Bearer ' + s.token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined
    });
    if (r.status === 401) return { ok: false, code: 'unauthorized', message: 'Jeton reddedildi (EXTENSION_TOKEN).' };
    if (r.status === 503) return { ok: false, code: 'disabled', message: 'Sunucuda EXTENSION_TOKEN ayarlı değil.' };
    if (r.status === 429) return { ok: false, code: 'rate_limited', message: 'Günlük analiz sınırı doldu ya da çok fazla deneme.' };
    if (r.status === 422) return { ok: false, code: 'invalid', message: 'Sunucu ilan verisini reddetti.' };
    if (!r.ok) return { ok: false, code: 'server', message: `Sunucu hatası (${r.status}).` };
    return { ok: true, data: await r.json() };
  } catch (e) {
    return { ok: false, code: 'offline', message: e && e.name === 'AbortError'
      ? 'Sunucu zamanında yanıt vermedi.' : 'Sunucuya ulaşılamadı. `arac panel serve` çalışıyor mu?' };
  } finally {
    clearTimeout(timer);
  }
}

const setResult = (tabId, value) => chrome.storage.session.set({ [KEY(tabId)]: { ...value, at: Date.now() } });

const fromSahibinden = (sender) => {
  try { return !!sender.tab && /(^|\.)sahibinden\.com$/.test(new URL(sender.url).hostname); } catch (_) { return false; }
};

async function handle(msg, sender) {
  const fromOurPage = sender.id === chrome.runtime.id;
  if (!fromOurPage) return { ok: false, code: 'forbidden' };

  switch (msg.type) {
    case 'getSettings': {
      const s = await getSettings();
      return { configured: !!s.token, autoAnalyze: s.autoAnalyze, autoBatch: s.autoBatch };   // token YOK
    }
    case 'analyze': {
      if (!fromSahibinden(sender)) return { ok: false, code: 'forbidden' };
      const tabId = sender.tab.id, p = msg.payload || {};
      const meta = { ilan_no: p.ilan_no, baslik: p.baslik, fiyat: p.fiyat, yil: p.yil, km: p.km, url: p.url };
      await setResult(tabId, { status: 'loading', meta });
      const s = await getSettings();
      const body = { ...p, page_path: msg.pagePath || undefined, ...(s.maxButce ? { max_butce: s.maxButce } : {}) };
      const res = await api('/api/v1/analyze', { body });
      await setResult(tabId, res.ok ? { status: 'ok', meta, data: res.data }
                                    : { status: 'error', meta, code: res.code, message: res.message });
      return res;
    }
    case 'batch': {
      if (!fromSahibinden(sender)) return { ok: false, code: 'forbidden' };
      return api('/api/v1/batch-evaluate', { body: { items: msg.items || [], page_path: msg.pagePath || undefined, remember: true } });
    }
    case 'detail:unreadable': {
      if (!fromSahibinden(sender)) return { ok: false, code: 'forbidden' };
      await setResult(sender.tab.id, { status: 'unreadable', eksik: msg.eksik || [] });
      return { ok: true };
    }
    case 'openPanel': {
      try { await chrome.sidePanel.open({ tabId: sender.tab.id }); return { ok: true }; }
      catch (_) { return { ok: false, code: 'gesture', message: 'Eklenti simgesine tıklayın.' }; }
    }
    case 'ping': return api('/api/v1/ping', { method: 'GET' });
    case 'panel:reanalyze':
    case 'panel:dump': {
      try {
        return await chrome.tabs.sendMessage(msg.tabId, { type: msg.type === 'panel:dump' ? 'dumpPage' : 'reanalyze' });
      } catch (_) { return { ok: false, code: 'no_page', message: 'Bu sekmede içerik betiği çalışmıyor.' }; }
    }
    default: return { ok: false, code: 'unknown' };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse, (e) => sendResponse({ ok: false, code: 'internal', message: String(e) }));
  return true;       // asenkron yanıt
});

chrome.runtime.onInstalled.addListener(async (info) => {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  if (info.reason === 'install') chrome.runtime.openOptionsPage();
});
chrome.runtime.onStartup.addListener(() => chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }));

// Eski sonuç yeni sayfada görünmesin; sekme kapanınca temizle
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove(KEY(tabId)));
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'loading' && change.url !== undefined) chrome.storage.session.remove(KEY(tabId));
});
