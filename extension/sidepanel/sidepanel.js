/* otoXray AI yan panel: yalnızca GÖSTERİR. Etiket üretmez; sunucudan geleni çizer. Tüm metinler textContent ile basılır
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
const card = (title) => { const c = el('section', 'card'); if (title) c.append(el('h2', '', title)); return c; };

async function activeTabId() {
  if (params.get('tabId')) return Number(params.get('tabId'));
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t ? t.id : null;
}

async function render() {
  const tabId = await activeTabId();
  const st = tabId == null ? null : (await chrome.storage.session.get(KEY(tabId)))[KEY(tabId)];
  app.replaceChildren(...view(st, tabId));
}

const VERDICT = {
  ALINIR: ['🟢', 'ALINIR', 'Ekspertize götürmeye değer'], DUSUNULEBILIR: ['🟡', 'DÜŞÜNÜLEBİLİR', 'Dikkatle değerlendir'],
  ALINMAZ: ['🔴', 'ALINMAZ', 'Elenen ilan']
};

function view(st, tabId) {
  if (!st) {
    const c = card();
    c.append(el('p', 'mute', 'Bir araç ilanı sayfası açın; analiz burada görünür.'), settingsBtn());
    return [c];
  }
  if (st.status === 'loading') return [head(st.meta), (() => { const c = card(); c.append(el('p', '', '⏳ Analiz ediliyor… (açıklama röntgeni birkaç saniye sürebilir)')); return c; })()];
  if (st.status === 'unreadable') return [unreadable(st, tabId)];
  if (st.status === 'error') return [head(st.meta), errorCard(st)];
  return renderOk(st, tabId);
}

function settingsBtn() {
  const b = el('button', '', 'Ayarlar');
  b.addEventListener('click', () => chrome.runtime.openOptionsPage());
  return b;
}

function head(meta) {
  const c = card();
  c.append(el('div', 'big', meta && meta.baslik ? meta.baslik : 'İlan'));
  if (meta && meta.fiyat) c.append(el('div', 'mute small', `${tl(meta.fiyat)} · ${meta.yil || ''} · ${(meta.km || 0).toLocaleString('tr-TR')} km`));
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
    el('p', 'small mute', 'Okuma kuralları gerçek sayfayla doğrulanmadı. Sayfa düzeni değişmiş olabilir.'));
  return c;
}

function renderOk(st, tabId) {
  const d = st.data, out = [];

  // 1) Karne başlığı
  const [emo, name, sub] = d.beklemede ? ['⏳', 'ANALİZ BEKLİYOR', 'LLM erişilemedi; temiz sayılmaz'] : VERDICT[d.etiket];
  const v = el('section', 'card verdict v-' + (d.beklemede ? 'WAIT' : d.etiket));
  v.id = 'verdict';
  v.append(el('span', 'emo', emo));
  const t = el('div'); t.append(el('b', '', name), el('span', 'mute small', sub));
  v.append(t);
  if (!d.beklemede) { const s = el('div', 'score', `${d.skor}/10`); s.append(el('div', 'mute small', `veri tamlığı %${Math.round(d.veri_tamlik * 100)}`)); v.append(s); }
  out.push(head(st.meta), v);

  // 2) Elenme nedenleri
  if (d.hard_fails && d.hard_fails.length) {
    const c = el('section', 'alert'); c.append(el('b', '', 'Elenme nedenleri'));
    const ul = el('ul'); d.hard_fails.forEach((h) => ul.append(el('li', '', h))); c.append(ul); out.push(c);
  }

  // 3) Piyasa
  const m = card('Piyasa özeti');
  const p = d.piyasa;
  m.append(row('İlan fiyatı', tl(st.meta.fiyat), 'big'));
  if (p && p.medyan > 0) {
    m.append(row(`Piyasa ilan medyanı (n=${p.n}, güven: ${p.guven})`, tl(p.medyan)));
    if (d.sapma_yuzde != null) {
      const s = d.sapma_yuzde;
      const pill = el('span', 'pill ' + (s < -20 ? 'warn' : s <= -5 ? 'good' : s > 5 ? 'bad' : ''),
        s < -20 ? `⚠ %${Math.abs(s)} ucuz: önce nedenini sor` : s <= -5 ? `%${Math.abs(s)} avantajlı` : s > 5 ? `%${s} pahalı` : 'piyasa değerinde');
      const r = el('div', 'row'); r.append(el('span', 'mute', 'Sapma'), pill); m.append(r);
    }
    if (p.n < 5) m.append(el('p', 'small mute', 'Emsal sayısı az: karşılaştırma güvenilir değil. Arama sayfalarını gezdikçe iyileşir.'));
  } else m.append(el('p', 'small mute', 'Henüz emsal yok. Aynı model için arama sayfalarını gezdikçe tarayıcınızda birikir.'));
  m.append(el('p', 'disc', 'Bunlar talep (ilan) fiyatlarıdır; gerçek satış fiyatı değildir.'));
  out.push(m);

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
  [['⚠️', d.eksiler], ['✅', d.artilar]].forEach(([ic, list]) => (list || []).forEach((s) => x.append(el('div', 'small', `${ic} ${s}${ic === '✅' ? ' (beyan)' : ''}`))));
  out.push(x);

  // 5) Teklif kutusu
  if (d.tavsiye_teklif) {
    const o = card('Teklif & pazarlık'); o.id = 'offer';
    const w = el('div', 'offer');
    w.append(row('Açılış teklifi', tl(d.tavsiye_teklif), 'big'), row('Üst sınır (yalnız sana)', tl(d.ust_sinir)));
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
    o.append(w); out.push(o);
  }

  // 6) Ekspertiz kontrol listesi
  const k = card('Ekspertiz kontrol listesi');
  const ul = el('ul'); (d.ekspertiz_kontrol_listesi || []).forEach((i) => ul.append(el('li', '', i)));
  k.append(ul, el('p', 'disc', d.uyari), el('p', 'disc', d.yasal_uyari || globalThis.OTOXRAY_DISCLAIMER)); out.push(k);

  // 7) Eylemler
  const act = el('div', 'actions');
  const re = el('button', '', '↻ Yeniden analiz et');
  re.addEventListener('click', () => chrome.runtime.sendMessage({ type: 'panel:reanalyze', tabId }));
  act.append(re, settingsBtn());
  out.push(act);
  return out;
}

function row(label, value, cls) {
  const r = el('div', 'row'); r.append(el('span', 'mute', label), el('span', cls || '', value)); return r;
}

chrome.storage.onChanged.addListener((_c, area) => { if (area === 'session') render(); });
chrome.tabs.onActivated.addListener(render);
chrome.tabs.onUpdated.addListener((_id, ch) => { if (ch.status) render(); });
render();
