/* otoXray AI — MV3 service worker: ağa çıkan TEK katman. Durum bellekte tutulmaz (worker her an öldürülebilir):
 * ayarlar, yerel piyasa deposu ve çözümleme önbelleği chrome.storage.local'da (YALNIZ kullanıcının kendi tarayıcısı),
 * sekme sonuçları chrome.storage.session'da. Token yalnızca burada okunur; sayfaya/içerik betiğine verilmez.
 * Desteklenen siteye HİÇBİR istek atılmaz; yalnızca kullanıcının açtığı sayfadan okunan veri yerel API'ye gider. */
importScripts('../lib/site.js');

// autoAnalyze varsayılan KAPALI: ilan açmak hak harcamaz; yapay zeka röntgeni paneldeki düğmeyle çalışır
const DEFAULTS = { apiBase: 'https://otoxray.cybergene.co', token: '', email: '', maxButce: null, autoAnalyze: false, autoBatch: true };
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

async function api(path, { method = 'POST', body, noAuth = false } = {}) {
  const s = await getSettings();
  if (!s.token && !noAuth) return { ok: false, code: 'no_token', message: 'Ayarlardan e-postanızla giriş yapın.' };
  const base = validBase(s.apiBase);
  if (!base) return { ok: false, code: 'bad_base', message: 'Sunucu adresi geçersiz.' };
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(base + path, {
      method, signal: ctl.signal, cache: 'no-store', credentials: 'omit',
      headers: { ...(noAuth ? {} : { Authorization: 'Bearer ' + s.token }), ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined
    });
    if (r.status === 401 && noAuth) return { ok: false, code: 'bad_code', message: 'Kod hatalı ya da süresi dolmuş.' };
    if (r.status === 401) return { ok: false, code: 'unauthorized', message: 'Oturum reddedildi: ayarlardan yeniden giriş yapın.' };
    if (r.status === 403 || r.status === 503) {     // erişim durduruldu/süresi doldu ya da e-posta kapalı: sunucunun kısa açıklaması
      let why = '';
      try { const j = await r.json(); why = typeof j.detail === 'string' ? j.detail.slice(0, 160) : ''; } catch (_) { /* yok */ }
      if (why) return { ok: false, code: r.status === 403 ? 'no_access' : 'unavailable', message: why };
    }
    if (r.status === 503) return { ok: false, code: 'disabled', message: 'Sunucuda EXTENSION_TOKEN ayarlı değil.' };
    if (r.status === 404) return { ok: false, code: 'outdated', message: 'Sunucu eski sürüm (bu özellik yok). otoxray-yeniden-baslat.cmd ile yeniden başlatın.' };
    if (r.status === 429) {          // sunucunun kendi açıklaması (kota/deneme) kısa ve güvenli bir metindir
      let why = '';
      try { const j = await r.json(); why = typeof j.detail === 'string' ? j.detail.slice(0, 120) : ''; } catch (_) { /* yok */ }
      return { ok: false, code: 'rate_limited', message: why || 'Günlük hakkınız doldu ya da çok fazla deneme.' };
    }
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
    let list = Object.entries(rows).filter(([id, r]) => validRow(id, r) && now - r.t < MK_TTL).sort((a, b) => b[1].t - a[1].t).slice(0, MK_PER_GROUP);
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
const validRow = (id, r) => /^[A-Za-z0-9_-]{1,20}$/.test(id) && r && Number.isInteger(r.y) && r.y >= 1950 && r.y <= 2100
  && Number.isInteger(r.k) && r.k >= 0 && r.k <= 3000000 && Number.isInteger(r.f) && r.f >= 1 && r.f <= 500000000;
const toComps = (rows) => Object.entries(rows).filter(([id, r]) => validRow(id, r)).map(([id, r]) => (r.s ? { id, yil: r.y, km: r.k, fiyat: r.f, seri: String(r.s).slice(0, 60) } : { id, yil: r.y, km: r.k, fiyat: r.f }));

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

// ------------------------------------------------------------------ Savaş Odası havuzu (YALNIZ bu tarayıcıda)
const HAVUZ = 'havuz', HAVUZ_MAX = 10;
const fromPanel = (sender) => String(sender.url || '').startsWith(chrome.runtime.getURL('sidepanel/'));
async function loadHavuz() { return (await chrome.storage.local.get(HAVUZ))[HAVUZ] || { items: {}, son: null }; }
const saveHavuz = (h) => chrome.storage.local.set({ [HAVUZ]: h });
/** Röntgen sonucunun karşılaştırma için gereken özeti (ilan metni değil) */
const ozet = (d) => (d && !d.beklemede && d.etiket ? {
  etiket: d.etiket, skor: d.skor, veri_tamlik: d.veri_tamlik, hard_fails: (d.hard_fails || []).slice(0, 10),
  eksiler: (d.eksiler || []).slice(0, 20), artilar: (d.artilar || []).slice(0, 20),
  sapma_yuzde: typeof d.sapma_yuzde === 'number' ? d.sapma_yuzde : null } : null);
const siteUrl = (u) => { try { const h = new URL(u).hostname; return (h === OTOXRAY_SITE_SUFFIX || h.endsWith('.' + OTOXRAY_SITE_SUFFIX)) ? u : null; } catch (_) { return null; } };

/** İlan açıldığında: sekmenin son yükü (panel "havuza ekle" için) + havuzdaysa görülen fiyat ve bilgi güncellemesi */
async function noteListing(tabId, p, pageUrl, data) {
  await chrome.storage.session.set({ ['p:' + tabId]: { p, url: siteUrl(pageUrl) } });
  const h = await loadHavuz(), it = h.items[p.ilan_no];
  if (!it) return;
  const son = it.gorulen[it.gorulen.length - 1];
  if (!son || son.f !== p.fiyat || Date.now() - son.t > 86400000) it.gorulen = [...it.gorulen, { t: Date.now(), f: p.fiyat }].slice(-30);
  Object.assign(it, { p, meta: { ...it.meta, fiyat: p.fiyat }, fiyat_degisti: p.fiyat_degisti, ilan_tarihi: p.ilan_tarihi });
  if (data && ozet(data)) it.sonuc = ozet(data);
  await saveHavuz(h);
}

/** Kullanıcının KENDİ gördüğü en yüksek fiyattan düşüş (yalnız havuzdaki ilan; siteye istek yok) */
async function gorulenDusus(p) {
  const it = (await loadHavuz()).items[p.ilan_no];
  const f = it ? it.gorulen.map((g) => g.f).filter((x) => typeof x === 'number') : [];
  const d = f.length ? Math.max(...f) - p.fiyat : 0;
  return d > 0 ? { gorulen_dusus: d } : {};
}

// ------------------------------------------------------------------ mesajlar
async function handle(msg, sender) {
  if (sender.id !== chrome.runtime.id) return { ok: false, code: 'forbidden' };

  switch (msg.type) {
    case 'getSettings': {
      const s = await getSettings();
      return { configured: !!s.token, email: s.email, autoAnalyze: s.autoAnalyze, autoBatch: s.autoBatch };   // token YOK
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
        await noteListing(tabId, p, msg.pageUrl, hit.data);
        await setResult(tabId, { status: 'ok', meta, data: hit.data });
        return { ok: true, data: hit.data, cached: true };
      }
      const since = Date.now();
      await setResult(tabId, { status: 'loading', meta, since });
      const emsal = group && mk.groups[group] ? nearby(toComps(mk.groups[group]), p.yil, p.km) : [];
      const body = { ...p, emsal, ...(s.maxButce ? { max_butce: s.maxButce } : {}), ...(await gorulenDusus(p)) };
      // ÖN HESAP (LLM'siz, anında): piyasa + yapıdan elenme nedenleri + ön teklif; LLM röntgeni beklenirken gösterilir.
      let finished = false;
      api('/api/v1/quick', { body }).then(async (q) => {
        if (finished) return;
        await setResult(tabId, q.ok ? { status: 'loading', meta, since, quick: q.data }
                                    : { status: 'loading', meta, since, quickError: q.message });
      });
      const res = await api('/api/v1/analyze', { body });
      finished = true;
      await noteListing(tabId, p, msg.pageUrl, res.ok ? res.data : null);
      await setResult(tabId, res.ok ? { status: 'ok', meta, data: res.data }
                                    : { status: 'error', meta, code: res.code, message: res.message });
      if (res.ok) {
        if (!res.data.beklemede) {      // LLM yoksa sonuç önbelleğe alınmaz: sonra yeniden denenebilsin
          await chrome.storage.local.set({ [cacheKey(p)]: { h: hash, t: Date.now(), data: res.data } });
          pruneCache();
        }
        if (group) {       // bu ilan da yerel emsal olur (yalnız sayısal nitelikler)
          mk.groups[group] = mk.groups[group] || {};
          mk.groups[group][p.ilan_no] = p.seri ? { y: p.yil, k: p.km, f: p.fiyat, t: Date.now(), s: String(p.seri).slice(0, 60) } : { y: p.yil, k: p.km, f: p.fiyat, t: Date.now() };
          mk.idx[p.ilan_no] = group;
          await chrome.storage.local.set({ [MK]: pruneMk(mk) });
        }
      }
      return res;
    }
    case 'preview': {            // ilan açılınca: yalnız LLM'siz ön hesap (hak harcamaz); önceki tam sonuç varsa o
      if (!fromSupportedSite(sender)) return { ok: false, code: 'forbidden' };
      const tabId = sender.tab.id, p = msg.payload || {};
      const meta = { ilan_no: p.ilan_no, baslik: p.baslik, fiyat: p.fiyat, yil: p.yil, km: p.km };
      const s = await getSettings();
      const mk = await loadMk();
      const group = mk.idx[p.ilan_no] || groupOfDetail(p);
      const hit = (await chrome.storage.local.get(cacheKey(p)))[cacheKey(p)];
      if (hit && hit.h === cacheHash(p, s.maxButce) && Date.now() - hit.t < CACHE_TTL) {
        await noteListing(tabId, p, msg.pageUrl, hit.data);
        await setResult(tabId, { status: 'ok', meta, data: hit.data });
        return { ok: true, data: hit.data, cached: true };
      }
      await noteListing(tabId, p, msg.pageUrl, hit && hit.data);
      const emsal = group && mk.groups[group] ? nearby(toComps(mk.groups[group]), p.yil, p.km) : [];
      const q = await api('/api/v1/quick', { body: { ...p, emsal, ...(s.maxButce ? { max_butce: s.maxButce } : {}), ...(await gorulenDusus(p)) } });
      await setResult(tabId, q.ok ? { status: 'preview', meta, quick: q.data }
                                  : { status: 'error', meta, code: q.code, message: q.message });
      return q.ok ? { ok: true, preview: true, data: q.data } : q;
    }
    case 'batch': {
      if (!fromSupportedSite(sender)) return { ok: false, code: 'forbidden' };
      const raw = (msg.items || []).filter((i) => validRow(i.ilan_no, { y: i.yil, k: i.km, f: i.fiyat }));
      const items = raw.map(({ ilan_no, fiyat, yil, km, seri }) => (seri ? { ilan_no, fiyat, yil, km, seri: String(seri).slice(0, 60) } : { ilan_no, fiyat, yil, km }));
      // Emsal grubu: satırın marka+serisi (ilan sayfalarıyla AYNI havuz). Okunamazsa sayfa yolu (eski davranış).
      // Metinle aramada yol "/otomobil" olduğundan yol grubu farklı modelleri karıştırırdı.
      const mk = await loadMk(), pathGroup = groupOfPath(msg.pagePath), now = Date.now(), touched = new Set();
      for (const i of raw) {
        const g = groupOfDetail({ marka: i.marka, seri: i.seri }) || pathGroup;
        if (!g) continue;
        mk.groups[g] = mk.groups[g] || {};
        mk.groups[g][i.ilan_no] = i.seri ? { y: i.yil, k: i.km, f: i.fiyat, t: now, s: String(i.seri).slice(0, 60) } : { y: i.yil, k: i.km, f: i.fiyat, t: now };
        mk.idx[i.ilan_no] = g;
        touched.add(g);
      }
      if (touched.size) await chrome.storage.local.set({ [MK]: pruneMk(mk) });
      const pool = Object.assign({}, ...[...touched].map((g) => mk.groups[g] || {}));
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
    case 'havuz:get':
    case 'havuz:add':
    case 'havuz:remove':
    case 'havuz:open':
    case 'havuz:compare': {
      if (!fromPanel(sender)) return { ok: false, code: 'forbidden' };
      const h = await loadHavuz();
      if (msg.type === 'havuz:get') return { ok: true, data: h, max: HAVUZ_MAX };
      if (msg.type === 'havuz:add') {
        const cur = (await chrome.storage.session.get('p:' + msg.tabId))['p:' + msg.tabId];
        if (!cur || !cur.p || !cur.p.ilan_no) return { ok: false, message: 'Önce bir ilan sayfası açın.' };
        const p = cur.p;
        if (!h.items[p.ilan_no] && Object.keys(h.items).length >= HAVUZ_MAX)
          return { ok: false, message: `Havuz dolu (${HAVUZ_MAX}/${HAVUZ_MAX}). Önce bir ilanı çıkarın.` };
        const hit = (await chrome.storage.local.get(cacheKey(p)))[cacheKey(p)];
        h.items[p.ilan_no] = h.items[p.ilan_no] || {
          ilan_no: p.ilan_no, url: cur.url, eklendi: Date.now(), gorulen: [{ t: Date.now(), f: p.fiyat }],
          meta: { baslik: p.baslik, fiyat: p.fiyat, yil: p.yil, km: p.km, marka: p.marka, seri: p.seri, paket: p.paket } };
        Object.assign(h.items[p.ilan_no], { p, ilan_tarihi: p.ilan_tarihi, fiyat_degisti: p.fiyat_degisti,
          sonuc: (hit && ozet(hit.data)) || h.items[p.ilan_no].sonuc || null });
        await saveHavuz(h);
        return { ok: true, data: h };
      }
      if (msg.type === 'havuz:remove') { delete h.items[msg.ilan_no]; await saveHavuz(h); return { ok: true, data: h }; }
      if (msg.type === 'havuz:open') {
        const it = h.items[msg.ilan_no], url = it && siteUrl(it.url);
        if (!url) return { ok: false, message: 'İlan adresi kayıtlı değil.' };
        await chrome.tabs.create({ url });                 // kullanıcının tıklamasıyla açılır; arka planda istek yok
        return { ok: true };
      }
      // havuz:compare — 2-5 ilan, her birinin röntgeni olmalı
      const secili = (msg.ids || []).map((id) => h.items[id]).filter(Boolean);
      if (secili.length < 2 || secili.length > 5) return { ok: false, message: '2 ile 5 arasında ilan seçin.' };
      const eksik = secili.filter((it) => !it.sonuc);
      if (eksik.length) return { ok: false, code: 'no_xray', message: 'Önce şu ilanların röntgenini çekin: ' + eksik.map((it) => it.meta.baslik).join(', ') };
      const ilanlar = secili.map((it) => {
        const p = it.p || {};
        return Object.assign({ ilan_no: it.ilan_no, baslik: (p.baslik || it.meta.baslik || '').slice(0, 200), fiyat: p.fiyat || it.meta.fiyat,
          yil: p.yil || it.meta.yil, km: p.km ?? it.meta.km, aciklama: (p.aciklama || '').slice(0, 8000),
          gorulen_fiyatlar: it.gorulen.map((g) => g.f).slice(-30), sonuc: it.sonuc },
          ...['marka', 'seri', 'paket', 'vites', 'yakit'].filter((k) => p[k]).map((k) => ({ [k]: String(p[k]).slice(0, 60) })),
          it.ilan_tarihi ? { ilan_tarihi: it.ilan_tarihi } : {}, typeof it.fiyat_degisti === 'boolean' ? { fiyat_degisti: it.fiyat_degisti } : {});
      });
      const r = await api('/api/v1/compare', { body: { ilanlar } });
      if (r.ok) { h.son = { t: Date.now(), ids: secili.map((it) => it.ilan_no), data: r.data }; await saveHavuz(h); }
      return r;
    }
    case 'rehber': {              // statik rehber (alım günü listesi): oturum boyunca bir kez çekilir
      const c = (await chrome.storage.session.get('rehber')).rehber;
      if (c && Date.now() - c.t < 3600000) return { ok: true, data: c.data };
      const r = await api('/api/v1/rehber', { method: 'GET' });
      if (r.ok) await chrome.storage.session.set({ rehber: { t: Date.now(), data: r.data } });
      return r;
    }
    case 'auth:kod':
    case 'auth:giris':
    case 'auth:cikis': {           // yalnız ayarlar sayfasından
      if (!String(sender.url || '').startsWith(chrome.runtime.getURL('options/'))) return { ok: false, code: 'forbidden' };
      if (msg.type === 'auth:kod') return api('/api/v1/auth/kod', { body: { email: String(msg.email || '').slice(0, 254) }, noAuth: true });
      if (msg.type === 'auth:giris') {
        const email = String(msg.email || '').slice(0, 254);
        const r = await api('/api/v1/auth/giris', { body: { email, kod: String(msg.kod || ''), cihaz: 'Chrome' }, noAuth: true });
        if (r.ok) await chrome.storage.local.set({ token: r.data.anahtar, email: r.data.email });
        return r.ok ? { ok: true, data: { email: r.data.email, ad: r.data.ad, kota: r.data.kota } } : r;   // anahtar sayfaya verilmez
      }
      await api('/api/v1/cikis', {});            // sunucuda bu cihazın anahtarını kapat (başarısız olsa da yerelde sil)
      await chrome.storage.local.remove(['token', 'email']);
      return { ok: true };
    }
    case 'feedback': {             // yalnız yan panelden; kullanıcının BİLEREK gönderdiği oy/sonuç/not
      if (!String(sender.url || '').startsWith(chrome.runtime.getURL('sidepanel/'))) return { ok: false, code: 'forbidden' };
      const f = msg.feedback || {};
      const body = { ilan_no: String(f.ilan_no || ''), etiket: f.etiket || null, skor: typeof f.skor === 'number' ? f.skor : null,
                     oy: f.oy || null, sonuc: f.sonuc || null, notu: f.notu ? String(f.notu).slice(0, 500) : null };
      return api('/api/v1/feedback', { body });
    }
    case 'clearLocalData': {         // kullanıcı kendi yerel verisini silebilir
      const all = await chrome.storage.local.get(null);
      await chrome.storage.local.remove(Object.keys(all).filter((k) => k === MK || k === HAVUZ || k.startsWith('ac:')));
      return { ok: true };
    }
    case 'panel:diagnose':
    case 'panel:analyze':
    case 'panel:reanalyze': {
      const type = { 'panel:diagnose': 'diagnose', 'panel:analyze': 'analyze-now', 'panel:reanalyze': 'reanalyze' }[msg.type];
      try { return await chrome.tabs.sendMessage(msg.tabId, { type }); }
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
