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

  // 3) Piyasa: ortalama (ilan medyanı), tipik aralık, sapma ve emsal sayısı
  const m = card('Piyasa özeti');
  m.id = 'market';
  const p = d.piyasa;
  m.append(row('İlan fiyatı', tl(st.meta.fiyat), 'big'));
  if (p && p.medyan > 0) {
    const avg = row('Piyasa ortalaması (ilan medyanı)', tl(p.medyan), 'big'); avg.id = 'avg'; m.append(avg);
    if (p.p25 && p.p75) m.append(row('Tipik aralık', `${tl(p.p25)} – ${tl(p.p75)}`));
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

  // 5) Teklif kutusu: açılış, hedef anlaşma, üst sınır + hesabın dayanağı
  const tk = d.teklif;
  if (tk || d.tavsiye_teklif) {
    const o = card('Teklif & pazarlık'); o.id = 'offer';
    const w = el('div', 'offer');
    const acilis = tk ? tk.acilis : d.tavsiye_teklif, ust = tk ? tk.ust_sinir : d.ust_sinir;
    w.append(row('Açılış teklifi', tl(acilis), 'big'));
    if (tk && tk.hedef) w.append(row('Makul anlaşma noktası', tl(tk.hedef)));
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
  act.append(re, settingsBtn(), diagBtn(tabId));
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
