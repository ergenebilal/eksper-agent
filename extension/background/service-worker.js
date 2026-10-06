/* otoXray AI — MV3 service worker: ağa çıkan TEK katman. Durum bellekte tutulmaz (worker her an öldürülebilir):
 * ayarlar, yerel piyasa deposu ve çözümleme önbelleği chrome.storage.local'da (YALNIZ kullanıcının kendi tarayıcısı),
 * sekme sonuçları chrome.storage.session'da. Token yalnızca burada okunur; sayfaya/içerik betiğine verilmez.
 * Desteklenen siteye HİÇBİR istek atılmaz; yalnızca kullanıcının açtığı sayfadan okunan veri yerel API'ye gider. */
importScripts('../lib/site.js');

const DEFAULTS = { apiBase: 'http://127.0.0.1:8991', token: '', maxButce: null, autoAnalyze: true, autoBatch: true };
const TIMEOUT_MS = 120000;                    // LLM çözümlemesi uzun sürebilir
const KEY = (tabId) => `r:${tabId}`;
const MK = 'mk';                              // yerel piyasa deposu (emsaller): yalnız sayısal nitelikler
const MK_TTL = 30 * 86400000, MK_GROUPS = 40, MK_PER_GROUP = 300;
const CACHE_TTL = 12 * 3600000, CACHE_MAX = 100;

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
    if (r.status === 422) {          // yalnız ALAN ADI ve kural mesajı gösterilir; girdi değeri (ilan metni) asla
      let why = '';
      try {
        const j = await r.json();
        why = (Array.isArray(j.detail) ? j.detail : []).slice(0, 3)
          .map((e) => `${(e.loc || []).filter((x) => x !== 'body').join('.')}: ${e.msg}`).join(' · ');
      } catch (_) { /* gövde okunamadı */ }
      return { ok: false, code: 'invalid', message: 'Sunucu ilan verisini reddetti' + (why ? ' (' + why + ')' : '.') };
    }
    if (!r.ok) return { ok: false, code: 'server', message: `Sunucu hatası (${r.status}).` };
    return { ok: true, data: await r.json() };
  } catch (e) {
    return { ok: false, code: 'offline', message: e && e.name === 'AbortError'
      ? 'Sunucu zamanında yanıt vermedi.' : 'Sunucuya ulaşılamadı. `arac xray serve` çalışıyor mu?' };
  } finally {
    clearTimeout(timer);
  }
}

const setResult = (tabId, value) => chrome.storage.session.set({ [KEY(tabId)]: { ...value, at: Date.now() } });

const fromSupportedSite = (sender) => {
  try {
    const h = new URL(sender.url).hostname;
    return !!sender.tab && (h === OTOXRAY_SITE_SUFFIX || h.endsWith('.' + OTOXRAY_SITE_SUFFIX));
  } catch (_) { return false; }
};

// ------------------------------------------------------------------ yerel piyasa deposu (kullanıcının tarayıcısı)
const fold = (s) => Array.from(String(s || '')).map((c) => ({ 'İ': 'i', 'I': 'i', 'ı': 'i', 'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g',
  'ü': 'u', 'Ü': 'u', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c' }[c] || c.toLowerCase())).join('').replace(/[^a-z0-9]+/g, ' ').trim();

async function loadMk() {
  const mk = (await chrome.storage.local.get(MK))[MK];
  return mk && mk.groups ? mk : { groups: {}, idx: {} };
}

function pruneMk(mk) {
  const now = Date.now();
  for (const [g, rows] of Object.entries(mk.groups)) {
    let list = Object.entries(rows).filter(([, r]) => now - r.t < MK_TTL).sort((a, b) => b[1].t - a[1].t).slice(0, MK_PER_GROUP);
    if (!list.length) delete mk.groups[g]; else mk.groups[g] = Object.fromEntries(list);
  }
  const keep = Object.entries(mk.groups).sort((a, b) => Math.max(...Object.values(b[1]).map((r) => r.t)) - Math.max(...Object.values(a[1]).map((r) => r.t))).slice(0, MK_GROUPS);
  mk.groups = Object.fromEntries(keep);
  for (const [id, g] of Object.entries(mk.idx)) if (!mk.groups[g] || !mk.groups[g][id]) delete mk.idx[id];
  return mk;
}

/** Arama sayfası grubu: adresin ilk yol parçası (kategori). Alan adı ya da kimlik içermez. */
const groupOfPath = (p) => { const seg = String(p || '').split('?')[0].split('/').filter(Boolean)[0]; return seg ? 'p:' + seg.toLowerCase() : null; };
const groupOfDetail = (pl) => (pl.marka && pl.seri ? 'm:' + fold(pl.marka + ' ' + pl.seri) : null);
const toComps = (rows) => Object.entries(rows).map(([id, r]) => ({ id, yil: r.y, km: r.k, fiyat: r.f }));

function nearby(comps, yil, km) {
  return comps.filter((c) => Math.abs(c.yil - yil) <= 2 && Math.abs(c.km - km) <= km * 0.5 + 1).slice(0, 200);
}

// ------------------------------------------------------------------ çözümleme önbelleği (yalnız bu tarayıcıda)
function hashOf(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16);
}
const cacheKey = (p) => 'ac:' + p.ilan_no;
const cacheHash = (p, maxButce) => hashOf([p.baslik, p.fiyat, p.km, p.yil, p.aciklama, JSON.stringify(p.parts), maxButce].join('|'));

async function pruneCache() {
  const all = await chrome.storage.local.get(null), now = Date.now();
  const rows = Object.entries(all).filter(([k]) => k.startsWith('ac:'));
  const dead = rows.filter(([, v]) => now - v.t > CACHE_TTL).map(([k]) => k);
  const live = rows.filter(([, v]) => now - v.t <= CACHE_TTL).sort((a, b) => b[1].t - a[1].t);
  await chrome.storage.local.remove([...dead, ...live.slice(CACHE_MAX).map(([k]) => k)]);
}

// ------------------------------------------------------------------ mesajlar
async function handle(msg, sender) {
  if (sender.id !== chrome.runtime.id) return { ok: false, code: 'forbidden' };

  switch (msg.type) {
    case 'getSettings': {
      const s = await getSettings();
      return { configured: !!s.token, autoAnalyze: s.autoAnalyze, autoBatch: s.autoBatch };   // token YOK
    }
    case 'analyze': {
      if (!fromSupportedSite(sender)) return { ok: false, code: 'forbidden' };
      const tabId = sender.tab.id, p = msg.payload || {};
      const meta = { ilan_no: p.ilan_no, baslik: p.baslik, fiyat: p.fiyat, yil: p.yil, km: p.km };
      const s = await getSettings();
      const mk = await loadMk();
      const group = mk.idx[p.ilan_no] || groupOfDetail(p);
      const hash = cacheHash(p, s.maxButce);
      const hit = msg.force ? null : (await chrome.storage.local.get(cacheKey(p)))[cacheKey(p)];
      if (hit && hit.h === hash && Date.now() - hit.t < CACHE_TTL) {
        await setResult(tabId, { status: 'ok', meta, data: hit.data });
        return { ok: true, data: hit.data, cached: true };
      }
      await setResult(tabId, { status: 'loading', meta });
      const emsal = group && mk.groups[group] ? nearby(toComps(mk.groups[group]), p.yil, p.km) : [];
      const res = await api('/api/v1/analyze', { body: { ...p, emsal, ...(s.maxButce ? { max_butce: s.maxButce } : {}) } });
      await setResult(tabId, res.ok ? { status: 'ok', meta, data: res.data }
                                    : { status: 'error', meta, code: res.code, message: res.message });
      if (res.ok) {
        if (!res.data.beklemede) {      // LLM yoksa sonuç önbelleğe alınmaz: sonra yeniden denenebilsin
          await chrome.storage.local.set({ [cacheKey(p)]: { h: hash, t: Date.now(), data: res.data } });
          pruneCache();
        }
        if (group) {       // bu ilan da yerel emsal olur (yalnız sayısal nitelikler)
          mk.groups[group] = mk.groups[group] || {};
          mk.groups[group][p.ilan_no] = { y: p.yil, k: p.km, f: p.fiyat, t: Date.now() };
          mk.idx[p.ilan_no] = group;
          await chrome.storage.local.set({ [MK]: pruneMk(mk) });
        }
      }
      return res;
    }
    case 'batch': {
      if (!fromSupportedSite(sender)) return { ok: false, code: 'forbidden' };
      const items = (msg.items || []).map(({ ilan_no, fiyat, yil, km }) => ({ ilan_no, fiyat, yil, km }));
      const mk = await loadMk(), group = groupOfPath(msg.pagePath), now = Date.now();
      const pageRows = Object.fromEntries(items.map((i) => [i.ilan_no, { y: i.yil, k: i.km, f: i.fiyat, t: now }]));
      if (group) {            // sayfada ZATEN görünen satırlar yerel emsal olarak birikir
        mk.groups[group] = { ...(mk.groups[group] || {}), ...pageRows };
        for (const id of Object.keys(pageRows)) mk.idx[id] = group;
        await chrome.storage.local.set({ [MK]: pruneMk(mk) });
      }
      const pool = group ? (mk.groups[group] || pageRows) : pageRows;
      const emsal = toComps(pool).slice(0, 300);
      return api('/api/v1/batch-evaluate', { body: { items, emsal } });
    }
    case 'detail:unreadable': {
      if (!fromSupportedSite(sender)) return { ok: false, code: 'forbidden' };
      await setResult(sender.tab.id, { status: 'unreadable', eksik: msg.eksik || [] });
      return { ok: true };
    }
    case 'openPanel': {
      try { await chrome.sidePanel.open({ tabId: sender.tab.id }); return { ok: true }; }
      catch (_) { return { ok: false, code: 'gesture', message: 'Eklenti simgesine tıklayın.' }; }
    }
    case 'ping': return api('/api/v1/ping', { method: 'GET' });
    case 'clearLocalData': {         // kullanıcı kendi yerel verisini silebilir
      const all = await chrome.storage.local.get(null);
      await chrome.storage.local.remove(Object.keys(all).filter((k) => k === MK || k.startsWith('ac:')));
      return { ok: true };
    }
    case 'panel:diagnose':
    case 'panel:reanalyze': {
      try { return await chrome.tabs.sendMessage(msg.tabId, { type: msg.type === 'panel:diagnose' ? 'diagnose' : 'reanalyze' }); }
      catch (_) { return { ok: false, code: 'no_page', message: 'Bu sekmede içerik betiği çalışmıyor.' }; }
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
