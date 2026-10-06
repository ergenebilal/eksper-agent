/* CyberOto AI yan panel: yalnızca GÖSTERİR. Etiket üretmez; sunucudan geleni çizer. Tüm metinler textContent ile basılır
 * (innerHTML yok): sunucu yanıtındaki alıntılar satıcı metnidir ve güvensizdir. Durum chrome.storage.session'dan okunur. */
const app = document.getElementById('app');
document.getElementById('legal').textContent = globalThis.OTOXRAY_DISCLAIMER;
const params = new URLSearchParams(location.search);       // ?tabId=... yalnız hata ayıklama/test için
const KEY = (id) => `r:${id}`;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
const tl = (n) => (n == null ? '—' : n.toLocaleString('tr-TR') + ' TL');
const card = (title) => { const c = el('section', 'sec'); if (title) c.append(el('h2', '', title)); return c; };

async function activeTabId() {
  if (params.get('tabId')) return Number(params.get('tabId'));
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t ? t.id : null;
}

let REHBER = null;                     // onaylı alım günü listesi (sunucudan, bir kez)
chrome.runtime.sendMessage({ type: 'rehber' }).then((r) => { if (r && r.ok) { REHBER = r.data; render(); } }).catch(() => {});

function rehberCard() {
  const a = REHBER && REHBER.alim_gunu;
  if (!a || !a.bolumler || !a.bolumler.length) return null;
  const d = document.createElement('details'); d.className = 'sec rehber'; d.id = 'alim-gunu';
  d.append(el('summary', '', 'Alım günü ve noter kontrol listesi'));
  a.bolumler.forEach((b) => {
    d.append(el('h3', '', b.baslik));
    const ul = el('ul', 'checklist'); b.maddeler.forEach((m) => ul.append(el('li', '', m))); d.append(ul);
  });
  if (a.uyari) d.append(el('p', 'disc', a.uyari));
  return d;
}

// ------------------------------------------------------------------ Aday Karşılaştırma (havuz yalnız bu tarayıcıda)
let VIEW = 'ilan';
let HV = null, HV_MAX = 10;
const SEL = new Set();
let COMPARE_MSG = '';
async function loadPool() {
  const r = await chrome.runtime.sendMessage({ type: 'havuz:get' }).catch(() => null);
  if (r && r.ok) { HV = r.data; HV_MAX = r.max || 10; for (const id of [...SEL]) if (!HV.items[id]) SEL.delete(id); }
}

function tabsEl() {
  const n = HV ? Object.keys(HV.items).length : 0;
  const t = el('nav', 'tabs');
  const a = el('button', VIEW === 'ilan' ? 'tab on' : 'tab', 'Bu ilan'); a.id = 'tab-ilan';
  const b = el('button', VIEW === 'havuz' ? 'tab on' : 'tab', `Havuz (${n}/${HV_MAX})`); b.id = 'tab-havuz';
  a.addEventListener('click', () => { VIEW = 'ilan'; render(); });
  b.addEventListener('click', () => { VIEW = 'havuz'; render(); });
  t.append(a, b);
  return t;
}

function poolBtn(meta, tabId) {
  const inPool = HV && meta && HV.items[meta.ilan_no];
  const wrap = el('div', 'pool-row');
  const b = el('button', inPool ? 'pooled' : '', inPool ? 'Havuzda ✓ · çıkar' : '📌 Havuza ekle'); b.id = 'havuz-add';
  const m = el('span', 'small mute');
  b.addEventListener('click', async () => {
    const r = await chrome.runtime.sendMessage(inPool ? { type: 'havuz:remove', ilan_no: meta.ilan_no } : { type: 'havuz:add', tabId });
    if (r && r.ok) { HV = r.data; render(); } else m.textContent = (r && r.message) || 'Eklenemedi.';
  });
  wrap.append(b, m);
  if (!inPool) wrap.append(el('span', 'small mute', 'Adayları karşılaştırmak için havuzda toplayın.'));
  return wrap;
}

const gunOnce = (iso) => { if (!iso) return null; const d = Math.round((Date.now() - new Date(iso + 'T00:00:00').getTime()) / 86400000); return d >= 0 ? d : null; };

function havuzView(tabId) {
  const items = HV ? Object.values(HV.items).sort((a, b) => b.eklendi - a.eklendi) : [];
  if (!items.length) {
    const c = el('section', 'empty');
    c.append(el('h2', '', 'Havuz boş'), el('p', 'mute', 'Beğendiğiniz ilanların panelinde “Havuza ekle”ye basın. 2-5 ilanı seçip yan yana karşılaştırabilirsiniz.'));
    return [c];
  }
  const out = [];
  const list = el('section', 'sec'); list.id = 'havuz-list';
  list.append(el('h2', '', 'Adaylar'), el('p', 'small mute', 'Karşılaştırmak için 2-5 ilan seçin. Her ilanın önce röntgeni çekilmiş olmalı.'));
  items.forEach((it) => {
    const card = el('div', 'havuz-item');
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = SEL.has(it.ilan_no);
    cb.setAttribute('aria-label', 'Karşılaştırmaya ekle: ' + (it.meta.baslik || it.ilan_no));
    cb.addEventListener('change', () => { cb.checked ? SEL.add(it.ilan_no) : SEL.delete(it.ilan_no); render(); });
    const body = el('div', 'hb');
    body.append(el('b', '', it.meta.baslik || it.ilan_no));
    body.append(el('div', 'small mute', `${tl(it.meta.fiyat)} · ${it.meta.yil || ''} · ${(it.meta.km || 0).toLocaleString('tr-TR')} km`));
    const chips = el('div', 'chips');
    if (it.sonuc) { const c = el('span', 'chip v-' + it.sonuc.etiket, `${VERDICT[it.sonuc.etiket][1]} · ${it.sonuc.skor}/10`); chips.append(c); }
    else chips.append(el('span', 'chip warn', 'Röntgen yok'));
    const g = gunOnce(it.ilan_tarihi); if (g !== null) chips.append(el('span', 'chip', `${g} gündür yayında`));
    if (it.fiyat_degisti) chips.append(el('span', 'chip', 'Fiyatı değişmiş'));
    const f = (it.gorulen || []).map((x) => x.f);
    if (f.length > 1 && Math.max(...f) > it.meta.fiyat) chips.append(el('span', 'chip good', `Sizin gördüğünüzden ${tl(Math.max(...f) - it.meta.fiyat)} düştü`));
    body.append(chips);
    const acts = el('div', 'hacts');
    const open = el('button', 'mini', 'Aç'); open.addEventListener('click', () => chrome.runtime.sendMessage({ type: 'havuz:open', ilan_no: it.ilan_no }));
    const rm = el('button', 'mini', 'Çıkar');
    rm.addEventListener('click', async () => { const r = await chrome.runtime.sendMessage({ type: 'havuz:remove', ilan_no: it.ilan_no }); if (r && r.ok) { HV = r.data; SEL.delete(it.ilan_no); render(); } });
    acts.append(open, rm);
    // R5.3: gerçek sonuç (ekspertiz / aldım) → kalibrasyon. Seçim bilerek yapılır; ilan metni gönderilmez.
    const ds = document.createElement('select'); ds.className = 'durum'; ds.setAttribute('aria-label', 'Sonuç: ' + (it.meta.baslik || it.ilan_no));
    SONUC.forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = v ? t : 'Sonuç ekle'; o.selected = (it.durum || '') === v; ds.append(o); });
    ds.addEventListener('change', async () => {
      const r = await chrome.runtime.sendMessage({ type: 'havuz:durum', ilan_no: it.ilan_no, sonuc: ds.value || null });
      if (r && r.ok) { HV = r.data; render(); }
    });
    body.append(ds);
    card.append(cb, body, acts);
    list.append(card);
  });
  out.push(list);

  const n = SEL.size;
  const cmp = el('section', 'xray-cta'); cmp.id = 'compare-box';
  const btn = el('button', 'pri', n >= 2 ? `${n} ilanı karşılaştır ve karar ver` : 'Karşılaştır ve karar ver'); btn.id = 'compare-btn';
  btn.disabled = n < 2 || n > 5;
  const msg = el('p', 'quota', COMPARE_MSG || (n > 5 ? 'En fazla 5 ilan seçebilirsiniz.' : '1 analiz hakkı kullanır; aynı seçimi tekrar karşılaştırmak ücretsiz.'));
  btn.addEventListener('click', async () => {
    btn.disabled = true; btn.textContent = 'Karşılaştırılıyor…';
    const r = await chrome.runtime.sendMessage({ type: 'havuz:compare', ids: [...SEL] });
    COMPARE_MSG = r && r.ok ? '' : ((r && r.message) || 'Karşılaştırılamadı.');
    if (r && r.ok) await loadPool();
    render();
  });
  cmp.append(el('h2', '', 'Karşılaştır ve karar ver'), btn, msg);
  out.push(cmp);
  if (HV && HV.son && HV.son.ids.every((id) => HV.items[id])) out.push(...compareResult(HV.son.data));
  return out;
}

function compareResult(d) {
  const by = Object.fromEntries(d.tablo.map((r) => [r.ilan_no, r]));
  const name = (id) => `${by[id].no}. ${by[id].baslik || id}`;
  const out = [];
  const box = el('section', 'sec'); box.id = 'compare-result';
  box.append(el('h2', '', 'Sonuç'));
  [['Fiyat/performans galibi', d.galip, d.anlatim.galip, 'good'], ['En riskli', d.en_riskli, d.anlatim.en_riskli, 'bad'],
   ['Pazarlık şansı en yüksek', d.pazarlik, d.anlatim.pazarlik, 'warn']].forEach(([t, id, txt, cls]) => {
    const c = el('div', 'verdict-card ' + cls);
    c.append(el('span', 'k', t), el('b', '', name(id)), el('p', 'small', txt));
    box.append(c);
  });
  if (d.ekspertiz_sirasi && d.ekspertiz_sirasi.length) {
    box.append(el('h3', 'sub', 'Ekspertize gitme sırası'));
    const ol = el('ol', 'order'); d.ekspertiz_sirasi.forEach((id) => ol.append(el('li', '', by[id].baslik || id))); box.append(ol);
  }
  const tbl = el('div', 'cmp-table');
  d.tablo.forEach((r) => {
    const row = el('div', 'cmp-row');
    row.append(el('b', '', `${r.no}. ${r.baslik || r.ilan_no}`));
    row.append(el('span', 'small', `${tl(r.fiyat)} · tahmini toplam ${tl(r.maliyet_alt)}${r.maliyet_ust !== r.maliyet_alt ? '–' + tl(r.maliyet_ust) : ''}`));
    row.append(el('span', 'small mute', `${VERDICT[r.etiket][1]} · ${r.skor}/10${r.ilan_gun !== null && r.ilan_gun !== undefined ? ` · ${r.ilan_gun} gün` : ''}${r.hard_fails.length ? ' · ' + r.hard_fails[0] : ''}`));
    tbl.append(row);
  });
  box.append(el('h3', 'sub', 'Tablo'), tbl,
    el('p', 'disc', (d.llm ? 'Gerekçe metnini yapay zeka yazdı; kararlar ve sayılar kurallarla hesaplandı. ' : 'Kararlar ve sayılar kurallarla hesaplandı. ') + d.uyari));
  out.push(box);
  return out;
}

async function render() {
  if (!HV) await loadPool();
  if (VIEW === 'havuz') { app.replaceChildren(tabsEl(), ...havuzView()); return; }
  const tabId = await activeTabId();
  const st = tabId == null ? null : (await chrome.storage.session.get(KEY(tabId)))[KEY(tabId)];
  BS = tabId == null ? null : (await chrome.storage.session.get('b:' + tabId))['b:' + tabId] || null;
  app.replaceChildren(tabsEl(), ...view(st, tabId));
}

const VERDICT = {
  ALINIR: ['🟢', 'Alınır', 'Ekspertize götürmeye değer'], DUSUNULEBILIR: ['🟡', 'Düşünülebilir', 'Dikkatle değerlendirin'],
  ALINMAZ: ['🔴', 'Alınmaz', 'Bu ilan elendi']
};
const scannedAt = new Set();          // tarama efekti her sonuç için yalnız bir kez

function loadingView(st) {
  const out = [head(st.meta)];
  const q = st.quick;
  const wait = el('section', 'wait');
  wait.id = 'waiting';
  const secs = Math.max(0, Math.round((Date.now() - (st.since || st.at || Date.now())) / 1000));
  const title = el('p', 'num'); title.append(el('span', 'pulse'), document.createTextNode(`Açıklama röntgeni yapılıyor… ${secs} sn`));
  wait.append(title,
              el('p', 'small mute', q ? 'Yapay zeka analizi genelde 15-40 saniye sürer. Aşağıdaki piyasa ve teklif ön hesabı bu sırada hazırdır.'
                                      : 'Yapay zeka analizi genelde 15-40 saniye sürer.'));
  if (st.quickError) wait.append(el('p', 'small warnbox', 'Ön hesap alınamadı: ' + st.quickError));
  out.push(wait);
  if (q) {
    if (q.elenme_nedenleri && q.elenme_nedenleri.length) {
      const c = el('section', 'alert'); c.append(el('b', '', 'Elenme nedenleri (anında tespit)'));
      const ul = el('ul'); q.elenme_nedenleri.forEach((h) => ul.append(el('li', '', h))); c.append(ul); out.push(c);
    }
    out.push(marketCard(q, st.meta));
    const oc = offerCard(q, true); if (oc) out.push(oc);
  }
  return out;
}

function xrayCard(q, tabId) {
  // Yapay zeka röntgeni: yalnız bu düğmeyle çalışır. Hak bilgisi açıkça yazılır; aynı ilan tekrar ücretsizdir.
  const c = el('section', 'xray-cta'); c.id = 'xray-cta';
  c.append(el('h2', '', 'Yapay zeka röntgeni'),
    el('p', 'small', 'Açıklamadaki gizli kusurları, tramer ve dolandırıcılık işaretlerini arar; karne, kanıtlı bulgular ve kesin teklif çıkarır.'));
  const k = q.kota;
  const kalanGun = k ? Math.max(k.limit - k.kullanilan, 0) : null;
  const kalanAy = k && k.aylik ? Math.max(k.aylik.limit - k.aylik.kullanilan, 0) : null;
  const bitti = !q.tekrar_ucretsiz && k && (kalanGun === 0 || kalanAy === 0);
  const btn = el('button', 'pri', 'Röntgeni çalıştır'); btn.id = 'run-xray';
  btn.disabled = !!bitti;
  btn.addEventListener('click', async () => {
    btn.disabled = true; btn.textContent = 'Başlatılıyor…';
    const r = await chrome.runtime.sendMessage({ type: 'panel:analyze', tabId });
    if (r && r.ok === false) { btn.disabled = false; btn.textContent = 'Röntgeni çalıştır'; note.textContent = r.message || 'Başlatılamadı.'; }
  });
  let txt;
  if (q.tekrar_ucretsiz) txt = 'Bu ilan için hakkınızı zaten kullandınız; tekrar çalıştırmak ücretsiz.';
  else if (!k) txt = 'Sahip anahtarı: sınırsız.';
  else if (bitti) txt = kalanAy === 0 ? 'Bu ayki analiz hakkınız doldu.' : 'Bugünkü analiz hakkınız doldu; yarın yenilenir.';
  else txt = `1 analiz hakkı kullanır. Bugün kalan: ${kalanGun}/${k.limit}` + (kalanAy !== null ? `, bu ay: ${kalanAy}` : '');
  const note = el('p', 'quota', txt); note.id = 'xray-note';
  c.append(btn, note);
  if ((q.elenme_nedenleri || []).length && !q.tekrar_ucretsiz) {
    c.append(el('p', 'warnbox small', 'Bu ilan ön hesapta zaten eleniyor; röntgen için hak harcamanız gerekmez.'));
  }
  return c;
}

function previewView(st, tabId) {
  const q = st.quick, out = [];
  const plate = el('section', 'plate v-WAIT'); plate.id = 'preview';
  plate.append(carLine(st.meta), el('p', 'small mute', 'Ön hesap: piyasa, yapıdan elenme nedenleri ve ön teklif. Hak harcanmadı.'));
  out.push(plate, poolBtn(st.meta, tabId));
  if (q.sema_uyarisi) { const w = el('section', 'alert'); w.id = 'sema-uyari'; w.append(el('b', '', 'Hasar şeması güvenilir değil'), el('p', 'small', q.sema_uyarisi)); out.push(w); }
  if (q.elenme_nedenleri && q.elenme_nedenleri.length) {
    const c = el('section', 'alert'); c.append(el('b', '', 'Elenme nedenleri (ön hesap)'));
    const ul = el('ul'); q.elenme_nedenleri.forEach((h) => ul.append(el('li', '', h))); c.append(ul); out.push(c);
  }
  out.push(xrayCard(q, tabId), marketCard(q, st.meta));
  { const cc = costCard(q.gercek_maliyet, st.meta); if (cc) out.push(cc); }
  { const sc = signalsCard(q.sinyaller); if (sc) out.push(sc); }
  const oc = offerCard(q, true); if (oc) out.push(oc);
  out.push(belgeCard(st.meta, tabId));
  const rc = rehberCard(); if (rc) out.push(rc);
  return out;
}

function view(st, tabId) {
  if (!st) {
    const c = el('section', 'empty');
    c.append(el('h2', '', 'Bir araç ilanı açın'),
      el('p', 'mute', 'İlan sayfasında analiz kendiliğinden başlar; karne, piyasa kıyası ve teklif burada görünür.'), settingsBtn());
    return [c];
  }
  if (st.status === 'loading') return loadingView(st);
  if (st.status === 'preview') return previewView(st, tabId);
  if (st.status === 'unreadable') return [unreadable(st, tabId)];
  if (st.status === 'error') return [head(st.meta), errorCard(st)];
  return renderOk(st, tabId);
}

function settingsBtn() {
  const b = el('button', '', 'Ayarlar');
  b.addEventListener('click', () => chrome.runtime.openOptionsPage());
  return b;
}

function carLine(meta) {
  const p = el('p', 'car');
  p.append(el('b', '', meta && meta.baslik ? meta.baslik : 'İlan'));
  if (meta && meta.fiyat) p.append(document.createTextNode(`${tl(meta.fiyat)}, ${meta.yil || ''} model, ${(meta.km || 0).toLocaleString('tr-TR')} km`));
  return p;
}

function head(meta) {
  const c = el('section', 'sec');
  c.append(carLine(meta));
  return c;
}

function errorCard(st) {
  const c = el('section', 'alert');
  c.append(el('b', '', 'Analiz yapılamadı'), el('p', '', st.message || 'Bilinmeyen hata'));
  if (['no_token', 'unauthorized', 'disabled', 'bad_base'].includes(st.code)) c.append(settingsBtn());
  return c;
}

function unreadable(st, tabId) {
  const c = el('section', 'alert');
  c.append(el('b', '', 'Sayfa okunamadı'),
    el('p', '', `Okunamayan alanlar: ${(st.eksik || []).join(', ')}. Eksik veri “iyi” sayılmaz; bu ilan için karar üretilmedi.`),
    el('p', 'small mute', 'Okuma kuralları gerçek sayfayla doğrulanmadı. Sayfa düzeni değişmiş olabilir. Aşağıdaki rapor yalnızca sayfanın yapısını içerir (kişisel veri yok).'));
  c.append(diagBtn(tabId));
  return c;
}

function diagBtn(tabId) {
  const b = el('button', '', '📋 Teşhis raporunu kopyala');
  b.addEventListener('click', async () => {
    const r = await chrome.runtime.sendMessage({ type: 'panel:diagnose', tabId });
    if (!r || !r.ok) { b.textContent = (r && r.message) || 'Rapor alınamadı'; return; }
    try { await navigator.clipboard.writeText(JSON.stringify(r.report, null, 1)); b.textContent = '✓ Kopyalandı: geliştiriciye yapıştırın'; }
    catch (_) { b.textContent = 'Kopyalanamadı'; }
  });
  return b;
}

function marketCard(d, meta) {
  // Piyasa: ortalama (ilan medyanı), tipik aralık, sapma ve emsal sayısı
  const m = card('Piyasa özeti');
  m.id = 'market';
  const p = d.piyasa;
  m.append(row('İlan fiyatı', tl(meta.fiyat), 'big'));
  if (p && p.medyan > 0) {
    const avg = row('Piyasa ortalaması (ilan medyanı)', tl(p.medyan), 'big'); avg.id = 'avg'; m.append(avg);
    if (p.p25 && p.p75) {
      m.append(row('Tipik aralık', `${tl(p.p25)} – ${tl(p.p75)}`));
      if (meta.fiyat) m.append(rangeBar(p, meta.fiyat));
    }
    if (d.sapma_yuzde != null) {
      const sp = d.sapma_yuzde;
      const pill = el('span', 'pill ' + (sp < -20 ? 'warn' : sp <= -5 ? 'good' : sp > 5 ? 'bad' : ''),
        sp < -20 ? `⚠ %${Math.abs(sp)} ucuz: önce nedenini sor` : sp <= -5 ? `%${Math.abs(sp)} avantajlı` : sp > 5 ? `%${sp} pahalı` : 'piyasa değerinde');
      const r = el('div', 'row'); r.append(el('span', 'mute', 'İlan / piyasa'), pill); m.append(r);
    }
    m.append(el('p', 'small mute', `${p.n} emsal (aynı seri) · güven: ${p.guven === 'yuksek' ? 'yüksek' : 'düşük'}`));
    if (p.n < (p.min_emsal || 5)) m.append(el('p', 'small mute', `Emsal az (en az ${p.min_emsal || 5} gerekir): ortalama güvenilir değil.`));
  } else {
    const none = el('p', 'small mute', `Henüz piyasa verisi yok (emsal: ${p ? p.n : 0}/${(p && p.min_emsal) || 5}). Bu aracın SERİSİ için bir arama sonuçları sayfası açın; sayfadaki ilanlar tarayıcınızda emsal olarak birikir ve ortalama burada görünür. Piyasa fiyatı tahmin edilmez.`);
    none.id = 'no-market'; m.append(none);
  }
  m.append(el('p', 'disc', 'Bunlar talep (ilan) fiyatlarıdır; gerçek satış fiyatı değildir.'));
  return m;
}

function rangeBar(p, fiyat) {
  // İlan fiyatının emsal aralığındaki yeri: bant = tipik aralık, çizgi = ortalama, kapsül = bu ilan
  const lo = Math.min(p.p25, fiyat, p.medyan) * 0.94, hi = Math.max(p.p75, fiyat, p.medyan) * 1.06;
  const pos = (v) => `${(((v - lo) / (hi - lo)) * 100).toFixed(2)}%`;
  const wrap = el('div'), bar = el('div', 'range');
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', `İlan fiyatı ${tl(fiyat)}; tipik aralık ${tl(p.p25)} ile ${tl(p.p75)} arası`);
  const band = el('span', 'band'); band.style.left = pos(p.p25); band.style.width = `calc(${pos(p.p75)} - ${pos(p.p25)})`;
  const med = el('span', 'med'); med.style.left = pos(p.medyan);
  const you = el('span', 'you'); you.style.left = pos(fiyat);
  bar.append(el('span', 'rail'), band, med, you);
  const lg = el('div', 'range-legend');
  lg.append(el('span', '', 'Ucuz'), el('span', '', 'çizgi: ortalama, kapsül: bu ilan'), el('span', '', 'Pahalı'));
  wrap.append(bar, lg);
  return wrap;
}

// ------------------------------------------------------------------ Belge röntgeni (R5.4 ekspertiz raporu, R5.1 tramer)
let BS = null;                                          // bu sekmenin son belge sonucu (session)
const BD = { tur: 'ekspertiz', metin: '', pdf: null, gorseller: [], pdfAd: '', msg: '', busy: false };   // taslak: yeniden çizimde kaybolmaz

function belgeCard(meta, tabId) {
  const c = card('Belge röntgeni'); c.id = 'belge';
  c.append(el('p', 'small mute', 'Ekspertiz raporunuzu ya da hasar kaydı (tramer) sorgunuzu ekleyin: ilanla çelişkileri, onarım aralığını ve üst sınır önerisini çıkarır. Belge saklanmaz.'));
  const seg = el('div', 'seg');
  [['ekspertiz', 'Ekspertiz raporu'], ['tramer', 'Hasar kaydı']].forEach(([k, t]) => {
    const b = el('button', BD.tur === k ? 'on' : '', t); b.dataset.tur = k;
    b.addEventListener('click', () => { BD.tur = k; render(); }); seg.append(b);
  });
  const ta = document.createElement('textarea'); ta.id = 'belge-metin'; ta.rows = 5; ta.maxLength = 30000; ta.value = BD.metin;
  ta.placeholder = BD.tur === 'tramer' ? 'Sorgu sonucunu (SMS ya da e-Devlet ekranı) buraya yapıştırın' : 'Rapor metnini buraya yapıştırın ya da PDF seçin';
  ta.addEventListener('input', () => { BD.metin = ta.value; });
  const fl = el('label', 'file'); const fi = document.createElement('input'); fi.type = 'file'; fi.id = 'belge-pdf';
  fi.accept = 'application/pdf,.pdf,image/jpeg,image/png,image/webp'; fi.multiple = true;
  fl.append(fi, el('span', '', BD.pdfAd || 'PDF ya da fotoğraf / ekran görüntüsü seç (en fazla 4 görsel)'));
  fi.addEventListener('change', async () => {
    const files = Array.from(fi.files || []); if (!files.length) return;
    BD.pdf = null; BD.gorseller = []; BD.pdfAd = ''; BD.msg = '';
    if (files[0].type === 'application/pdf' || /\.pdf$/i.test(files[0].name)) {
      const f = files[0];
      if (f.size > 4 * 1024 * 1024) { BD.msg = 'PDF en fazla 4 MB olabilir.'; render(); return; }
      BD.pdf = (await dataUrl(f)).split(',')[1] || null; BD.pdfAd = 'PDF: ' + f.name.slice(0, 60);
    } else {
      const imgs = files.filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type)).slice(0, 4);
      if (!imgs.length) { BD.msg = 'Yalnız PDF, JPEG, PNG ya da WebP seçin.'; render(); return; }
      try { BD.gorseller = await Promise.all(imgs.map(kucult)); } catch (_) { BD.msg = 'Görsel okunamadı.'; render(); return; }
      BD.pdfAd = `${imgs.length} görsel seçildi` + (files.length > 4 ? ' (ilk 4)' : '');
    }
    render();
  });
  const go = el('button', 'pri', BD.busy ? 'Belge okunuyor…' : 'Belgeyi analiz et'); go.id = 'belge-go'; go.disabled = BD.busy;
  go.addEventListener('click', async () => {
    BD.busy = true; BD.msg = ''; render();
    const r = await chrome.runtime.sendMessage({ type: 'belge', tabId, tur: BD.tur, metin: BD.metin, pdf_b64: BD.pdf, gorseller: BD.gorseller });
    BD.busy = false; BD.msg = r && r.ok ? '' : ((r && r.message) || 'Belge okunamadı.');
    if (r && r.ok) { BD.metin = ''; BD.pdf = null; BD.gorseller = []; BD.pdfAd = ''; }
    render();
  });
  c.append(seg, ta, fl);
  if (BD.gorseller.length) c.append(el('p', 'small mute', 'Fotoğraf, okunmak için yapay zeka hizmetine gönderilir; okunan metindeki ad, plaka, şasi ve telefon gizlenir. İsterseniz bu alanları kapatarak çekin.'));
  c.append(go, el('p', 'quota', BD.msg || '1 analiz hakkı kullanır; aynı belgeyi tekrar okumak ücretsiz.'));
  if (BS && BS.data && (!meta || !BS.ilan_no || BS.ilan_no === meta.ilan_no)) c.append(belgeSonuc(BS.data));
  return c;
}

const dataUrl = (blob) => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = no; r.readAsDataURL(blob); });

/** Fotoğrafı tarayıcıda küçültür (en uzun kenar 2000 px, JPEG): yükleme hızlı, görsel okuma ucuz; EXIF yönü uygulanır. */
async function kucult(file) {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
  const k = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
  const cv = document.createElement('canvas'); cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
  cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
  const blob = await new Promise((ok) => cv.toBlob(ok, 'image/jpeg', 0.85));
  return (await dataUrl(blob)).split(',')[1];
}

function belgeSonuc(d) {
  const box = el('div', 'belge-sonuc'); box.id = 'belge-sonuc';
  box.append(el('p', 'num', d.ozet));
  const cl = (d.celiskiler || []);
  if (cl.length) {
    const ul = el('ul', 'sig');
    cl.forEach((c) => { const li = el('li', 'bk-' + c.tur, c.mesaj); if (c.alinti) li.append(el('q', 'small', c.alinti)); ul.append(li); });
    box.append(el('h3', 'sub', 'İlanla karşılaştırma'), ul);
  }
  if (d.maliyet && d.maliyet.kalemler.length) {
    const ul = el('ul', 'costs');
    d.maliyet.kalemler.forEach((k) => {
      const li = el('li', 'cost'); const top = el('div', 'row');
      top.append(el('span', '', k.ad), el('span', 'num', k.aralik ? `${tl(k.aralik[0])} – ${tl(k.aralik[1])}` : 'tutar onayı bekliyor'));
      li.append(top, el('q', 'small', k.alinti)); ul.append(li);
    });
    box.append(el('h3', 'sub', 'Rapordaki onarımlar'), ul);
  }
  if (d.teklif) {
    const r = row('Belge sonrası üst sınır önerisi', tl(d.teklif.ust_sinir), 'big'); r.id = 'belge-ust'; box.append(r);
    const ul = el('ul', 'sig'); d.teklif.dayanak.forEach((x) => ul.append(el('li', 'small', x))); box.append(ul);
  }
  if (d.dusen_bulgu) box.append(el('p', 'small mute', `${d.dusen_bulgu} bulgu belgede birebir bulunamadığı için gösterilmedi.`));
  if (d.okunan_metin) {                               // fotoğraftan okunan metin: kullanıcı belgenin aslıyla karşılaştırabilsin
    const det = document.createElement('details'); det.id = 'belge-okunan';
    det.append(el('summary', 'small', 'Fotoğraftan okunan metin (kişisel bilgiler gizlendi)'), el('pre', 'okunan', d.okunan_metin));
    box.append(det);
  }
  box.append(el('p', 'disc', d.uyari));
  return box;
}

function signalsCard(sg) {
  // Satıcı ve piyasa sinyalleri (R4): nesnel dil, alıntılı ya da veriye dayalı; kişi hakkında hüküm yok.
  if (!sg) return null;
  const s = sg.satis, t = sg.ticari, lq = sg.likidite;
  const hasS = s && s.nedenler && s.nedenler.length, hasL = lq && (lq.bant || (lq.notlar && lq.notlar.length));
  if (!hasS && !t && !hasL) return null;
  const c = card('Satış ve piyasa sinyalleri'); c.id = 'signals';
  if (hasS) {
    const r = row('Hızlı satış motivasyonu', { dusuk: 'Düşük', orta: 'Orta', yuksek: 'Yüksek' }[s.bant]); r.classList.add('sig-' + s.bant); c.append(r);
    if (s.indirim_ivmesi) c.append(el('span', 'tag', 'Yüksek indirim ivmesi'));
    const ul = el('ul', 'sig');
    s.nedenler.forEach((n) => { const li = el('li', '', n.etiket); if (n.alinti) li.append(el('q', 'small', n.alinti)); ul.append(li); });
    c.append(ul);
  }
  if (t) {
    const b = el('div', t.durum === 'sinyal' ? 'warnbox small' : 'small mute'); b.id = 'ticari';
    b.append(el('b', '', t.durum === 'sinyal' ? 'Ticari satıcı sinyali' : 'Ticari satış'), el('p', 'small', t.mesaj));
    (t.alintilar || []).slice(0, 3).forEach((a) => b.append(el('q', 'small', a)));
    c.append(b);
  }
  if (hasL) {
    if (lq.bant) c.append(row('Piyasa hızı', { hizli: 'Hızlı', orta: 'Orta', yavas: 'Yavaş' }[lq.bant]), el('p', 'small mute', lq.gerekce));
    (lq.notlar || []).forEach((n) => c.append(el('p', 'small mute', n)));
  }
  c.append(el('p', 'disc', 'Sinyaller ilan metni ve ilan verisinden çıkarılır; satıcı hakkında yargı değildir. ' + ((lq && lq.uyari) || '')));
  return c;
}

function costCard(gm, meta) {
  // Tahmini gerçek maliyet: ilanın söylediği yapılacak masraflar (alıntılı) + km'si gelmiş bakım (olası). Tutar ARALIK.
  if (!gm || !gm.kalemler || !gm.kalemler.length) return null;
  const c = card('Tahmini gerçek maliyet'); c.id = 'cost';
  const tutarli = gm.kalemler.some((k) => k.aralik);
  if (tutarli) {
    c.append(row('İlan fiyatı', tl(meta.fiyat)));
    const r = row('Masraflarla birlikte', `${tl(gm.toplam_alt)} – ${tl(gm.toplam_ust)}`, 'big'); r.id = 'cost-total'; c.append(r);
  }
  const ul = el('ul', 'costs');
  gm.kalemler.forEach((k) => {
    const li = el('li', 'cost ' + k.kesinlik);
    const top = el('div', 'row');
    top.append(el('span', '', k.ad), el('span', 'num', k.aralik ? `${tl(k.aralik[0])} – ${tl(k.aralik[1])}` : 'tutar onayı bekliyor'));
    li.append(top);
    if (k.alinti) li.append(el('q', 'small', k.alinti));
    if (k.kesinlik === 'olasi') li.append(el('span', 'tag', 'Olası: ' + (k.neden || 'yapıldığı belirtilmemiş')));
    ul.append(li);
  });
  c.append(ul, el('p', 'disc', 'Tahmini aralıktır (işçilik dahil, ' + (gm.segment === 'bilinmiyor' ? 'araç sınıfı bilinmediği için geniş aralık' : 'araç sınıfına göre') +
    '). Kesin fiyat için ustadan teklif alın. Olası kalemler teklife yansıtılmaz.'));
  return c;
}

function offerCard(d, onhesap) {
  // Teklif kutusu: açılış, hedef anlaşma, üst sınır + hesabın dayanağı
  const tk = d.teklif;
  if (tk || d.tavsiye_teklif) {
    const o = card(onhesap ? 'Teklif & pazarlık (ön hesap)' : 'Teklif & pazarlık'); o.id = 'offer';
    if (onhesap) o.append(el('p', 'small warnbox', 'Ön hesap: açıklama analizi (tramer, kusur) bitince kesinleşir.'));
    const w = el('div', 'offer');
    const acilis = tk ? tk.acilis : d.tavsiye_teklif, ust = tk ? tk.ust_sinir : d.ust_sinir;
    w.append(row('Açılış teklifi', tl(acilis), 'big'));
    if (tk && (tk.anlasma || tk.hedef)) w.append(row('Makul anlaşma noktası', tl(tk.anlasma || tk.hedef)));
    w.append(row('Üst sınır (yalnız sana)', tl(ust)));
    if (tk && tk.kaynak === 'ilan') {
      w.append(el('p', 'small warnbox', 'Piyasa verisi olmadığı için bu teklif yalnızca ilan fiyatı ve ilandaki kusurlara göre hesaplandı. Emsal bulununca daha güvenilir olur.'));
    }
    if (tk && tk.dayanak && tk.dayanak.length) {
      const det = document.createElement('details'); det.id = 'basis';
      det.append(el('summary', 'small', 'Nasıl hesaplandı?'));
      const ul2 = el('ul', 'small'); tk.dayanak.forEach((x) => ul2.append(el('li', '', x))); det.append(ul2);
      w.append(det);
    }
    if (d.whatsapp_metni) {
      const b = el('button', 'pri', '📋 WhatsApp teklif metnini kopyala');
      b.id = 'copy';
      b.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(d.whatsapp_metni); b.textContent = '✓ Kopyalandı'; }
        catch (_) { b.textContent = 'Kopyalanamadı'; }
        setTimeout(() => (b.textContent = '📋 WhatsApp teklif metnini kopyala'), 2500);
      });
      w.append(b, el('p', 'disc', 'Metin yalnız kopyalanır; göndermeyi sen yaparsın. Üst sınır metne girmez.'));
    }
    o.append(w);
    return o;
  }
  return null;
}


function renderOk(st, tabId) {
  const d = st.data, out = [];

  // 1) Karne başlığı
  const [, name, sub] = d.beklemede ? ['', 'Analiz bekliyor', 'Yapay zekaya ulaşılamadı; temiz sayılmaz'] : VERDICT[d.etiket];
  const v = el('section', 'plate v-' + (d.beklemede ? 'WAIT' : d.etiket));
  v.id = 'verdict';
  v.setAttribute('aria-label', `Karar: ${name}`);
  v.append(carLine(st.meta));
  const vr = el('div', 'verdict-row');
  // Elenen ilanda halka puan göstermez: yüksek puan + 🔴 "iyi" gibi okunmasın (elenme puandan bağımsızdır)
  const elendi = !d.beklemede && d.etiket === 'ALINMAZ' && (d.hard_fails || []).length > 0;
  const ring = el('div', 'ring');
  ring.style.setProperty('--p', d.beklemede ? 0 : elendi ? 100 : Math.round(d.skor * 10));
  const sc = el('span', '', d.beklemede ? '—' : elendi ? '✕' : String(d.skor));
  sc.append(el('small', '', elendi ? 'elendi' : 'güven / 10'));
  ring.append(sc);
  const t = el('div');
  t.append(el('div', 'word', name), el('span', 'word-sub', sub));
  if (elendi) t.append(el('span', 'word-meta', `Puan ${d.skor}/10, ama aşağıdaki neden ilanı tek başına eler`));
  else if (!d.beklemede) t.append(el('span', 'word-meta', `Veri tamlığı %${Math.round(d.veri_tamlik * 100)}`));
  vr.append(ring, t);
  v.append(vr);
  if (!scannedAt.has(st.at)) { scannedAt.add(st.at); v.append(el('span', 'scan')); }   // sonuç ilk geldiğinde tek tarama
  out.push(v);

  // 2) Elenme nedenleri
  if (d.hard_fails && d.hard_fails.length) {
    const c = el('section', 'alert'); c.append(el('b', '', 'Elenme nedenleri'));
    const ul = el('ul'); d.hard_fails.forEach((h) => ul.append(el('li', '', h))); c.append(ul); out.push(c);
  }

  out.push(marketCard(d, st.meta));
  { const cc = costCard(d.gercek_maliyet, st.meta); if (cc) out.push(cc); }
  { const sc = signalsCard(d.sinyaller); if (sc) out.push(sc); }

  // 4) Gizli kusur röntgeni
  const x = card('Gizli kusur röntgeni');
  x.id = 'xray';
  if (d.beklemede) x.append(el('p', 'mute', 'Açıklama analizi bekliyor.'));
  else if (!d.kanitlar.length) x.append(el('p', 'mute', 'Açıklamada kanıtlı bulgu yok. (Bu, sorun olmadığı anlamına gelmez.)'));
  d.kanitlar.forEach((k) => {
    const e = el('div', 'ev'); e.append(el('span', 'dot ' + (k.tur === 'dolandiricilik' ? 'olumsuz' : k.tur)));
    const b = el('div'); b.append(el('b', '', k.etiket), document.createElement('br'), el('q', 'small', k.alinti));
    e.append(b); x.append(e);
  });
  [['neg', d.eksiler], ['pos', d.artilar]].forEach(([k, list]) => (list || []).forEach((s) => x.append(el('div', 'line ' + k, `${s}${k === 'pos' ? ' (beyan)' : ''}`))));
  out.push(x);

  { const oc = offerCard(d, false); if (oc) out.push(oc); }

  // 6) Satıcıya sorulacaklar (öncelik sıralı) + ekspertiz kontrol listesi (araca özel + her araçta)
  { const sc = questionsCard(d); if (sc) out.push(sc); }
  out.push(checklistCard(d));
  out.push(belgeCard(st.meta, tabId));
  { const rc = rehberCard(); if (rc) out.push(rc); }

  if (!d.beklemede) out.push(feedbackCard(d, st.meta));
  if (d.kota) out.push(el('p', 'quota', `Bugünkü analiz hakkın: ${Math.max(d.kota.limit - d.kota.kullanilan, 0)}/${d.kota.limit}`));

  out.push(poolBtn(st.meta, tabId));
  // 7) Eylemler
  const act = el('div', 'actions');
  const re = el('button', '', '↻ Yeniden analiz et');
  re.addEventListener('click', () => chrome.runtime.sendMessage({ type: 'panel:reanalyze', tabId }));
  act.append(re, settingsBtn(), diagBtn(tabId));
  out.push(act);
  return out;
}

const SONUC = [['', 'Ekspertiz sonucu (varsa)'], ['ekspertiz_temiz', 'Ekspertiz temiz çıktı'],
  ['ekspertiz_kucuk_kusur', 'Küçük kusur çıktı'], ['ekspertiz_agir_kusur', 'Ağır kusur çıktı'], ['gitmedim', 'Ekspertize gitmedim'],
  ['satin_aldim', 'Satın aldım'], ['almadim', 'Almadım']];

function feedbackCard(d, meta) {
  // Geri bildirim: kullanıcının bilerek gönderdiği oy/sonuç/not. Açıklama metni GÖNDERİLMEZ.
  const c = card('Bu analiz işine yaradı mı?'); c.id = 'feedback';
  let oy = null;
  const up = el('button', '', '👍'), down = el('button', '', '👎');
  const mark = () => { up.className = oy === 'pos' ? 'on' : ''; down.className = oy === 'neg' ? 'on' : ''; };
  up.addEventListener('click', () => { oy = 'pos'; mark(); });
  down.addEventListener('click', () => { oy = 'neg'; mark(); });
  const btns = el('div', 'vote'); btns.append(up, down);
  up.setAttribute('aria-label', 'Faydalı'); down.setAttribute('aria-label', 'Faydalı değil');
  const sel = document.createElement('select'); sel.id = 'fb-sonuc';
  SONUC.forEach(([v, t]) => { const o = el('option', '', t); o.value = v; sel.append(o); });
  const note = document.createElement('textarea'); note.id = 'fb-not'; note.maxLength = 500; note.rows = 2;
  note.placeholder = 'Not (isteğe bağlı): neyi yanlış/doğru buldu?';
  const send = el('button', 'pri', 'Gönder'); send.id = 'fb-send';
  const msg = el('p', 'small mute fb-msg');
  send.addEventListener('click', async () => {
    if (!oy && !sel.value && !note.value.trim()) { msg.textContent = 'Önce 👍/👎, sonuç ya da not seç.'; return; }
    send.disabled = true;
    const r = await chrome.runtime.sendMessage({ type: 'feedback', feedback: {
      ilan_no: meta && meta.ilan_no, etiket: d.etiket, skor: d.skor, oy, sonuc: sel.value || null, notu: note.value.trim() || null } });
    msg.textContent = r && r.ok ? '✓ Teşekkürler, iletildi.' : (r && r.message) || 'Gönderilemedi.';
    send.disabled = !!(r && r.ok);
  });
  c.append(btns, sel, note, send, msg,
    el('p', 'disc', 'Gönderdiğin oy, ekspertiz sonucu, not ve ilan numarası ürünü geliştirmek için saklanır. İlan açıklaması gönderilmez; nottaki telefon numaraları maskelenir.'));
  return c;
}

const KAYNAK = { sema: 'Hasar şeması', bulgu: 'Açıklama', kronik: 'Model bilgisi', bakim: 'Bakım zamanı',
                 veri: 'Eksik bilgi', piyasa: 'Piyasa' };

function questionsCard(d) {
  const qs = d.soru_carsafi || [];
  if (!qs.length) return null;
  const c = card('Satıcıya sorulacaklar'); c.id = 'questions';
  c.append(el('p', 'small mute', 'Aramadan önce: önem sırasına göre. Cevaba göre ne yapacağınız her sorunun altında.'));
  const ol = el('ol', 'qlist');
  qs.forEach((q) => {
    const li = el('li', 'q p' + q.oncelik);
    li.append(el('b', '', q.soru), el('span', 'why', q.neden), el('span', 'then', q.cevap_ise));
    ol.append(li);
  });
  const b = el('button', '', 'Soruları kopyala'); b.id = 'copy-questions';
  b.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(d.soru_metni || qs.map((q, i) => `${i + 1}. ${q.soru}`).join('\n')); b.textContent = 'Kopyalandı'; }
    catch (_) { b.textContent = 'Kopyalanamadı'; }
    setTimeout(() => (b.textContent = 'Soruları kopyala'), 2500);
  });
  c.append(ol, b, el('p', 'disc', 'Yalnız kopyalanır; göndermeyi siz yaparsınız.'));
  return c;
}

function checklistCard(d) {
  const k = card('Ekspertiz kontrol listesi'); k.id = 'checklist';
  const e = d.ekspertiz;
  if (e && e.bu_aracta && e.bu_aracta.length) {
    k.append(el('h3', 'sub', 'Bu araçta özellikle'));
    const ul = el('ul', 'checklist special');
    e.bu_aracta.forEach((x) => { const li = el('li', '', x.madde); li.append(el('span', 'src', KAYNAK[x.kaynak] || x.kaynak)); ul.append(li); });
    k.append(ul, el('h3', 'sub', 'Her araçta'));
  }
  const base = e && e.genel ? e.genel : (d.ekspertiz_kontrol_listesi || []);
  const ul2 = el('ul', 'checklist'); base.forEach((i) => ul2.append(el('li', '', i)));
  k.append(ul2, el('p', 'disc', d.uyari));               // yasal uyarı altbilgide (#legal) tek kez
  return k;
}

function row(label, value, cls) {
  const r = el('div', 'row'); r.append(el('span', 'mute', label), el('span', cls || '', value)); return r;
}

chrome.storage.onChanged.addListener((c, area) => {
  if (area === 'local' && c.havuz) { HV = c.havuz.newValue || { items: {}, son: null }; render(); }
  if (area === 'session' && !(document.activeElement && document.activeElement.id === 'belge-metin')) render();   // yazarken odak kaybolmasın
});
setInterval(() => { if (document.getElementById('waiting')) render(); }, 1000);   // bekleme sayacı
chrome.tabs.onActivated.addListener(render);
chrome.tabs.onUpdated.addListener((_id, ch) => { if (ch.status) render(); });
render();
