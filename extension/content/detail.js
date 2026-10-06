/* İlan detay sayfası: veriyi okur → service worker'a yollar (ağa YALNIZ o çıkar) → vurgular ve küçük rozet gösterir.
 * Bu betik sahibinden'e ek istek ATMAZ; yalnızca kullanıcının açtığı sayfayı okur. Token'a erişimi yoktur. */
(function () {
  const A = globalThis.AracX;
  if (!A || A._detailLoaded) return;
  A._detailLoaded = true;

  const send = (msg) => chrome.runtime.sendMessage(msg).catch((e) => ({ ok: false, code: 'extension', message: String(e) }));
  const LABEL = {
    ALINIR: ['🟢', 'Ekspertize götürmeye değer'], DUSUNULEBILIR: ['🟡', 'Düşünülebilir'], ALINMAZ: ['🔴', 'Alınmaz']
  };

  // ---- küçük rozet (shadow DOM: sayfa CSS'inden yalıtılmış)
  const host = document.createElement('div');
  host.id = 'aracx-badge-host';
  const root = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = `
    .b{all:initial;position:fixed;right:16px;bottom:16px;z-index:2147483647;font:600 13px system-ui,sans-serif;
       background:#0f172a;color:#f1f5f9;border:1px solid #475569;border-radius:999px;padding:8px 14px;cursor:pointer;
       box-shadow:0 4px 14px rgba(0,0,0,.35)}
    .b[data-t=ALINIR]{border-color:#16a34a}.b[data-t=DUSUNULEBILIR]{border-color:#ca8a04}.b[data-t=ALINMAZ]{border-color:#dc2626}`;
  const badge = document.createElement('button');
  badge.className = 'b';
  badge.type = 'button';
  root.append(style, badge);
  document.documentElement.appendChild(host);
  badge.addEventListener('click', () => send({ type: 'openPanel' }));

  function setBadge(text, tur) {
    badge.textContent = text;
    if (tur) badge.setAttribute('data-t', tur); else badge.removeAttribute('data-t');
  }

  let current = null;     // son okunan {payload, descEl}

  async function run() {
    const ex = A.extractDetail(document, location);
    if (!ex.ok) {
      setBadge('Araç Eksper: sayfa okunamadı', null);
      await send({ type: 'detail:unreadable', eksik: ex.eksik });
      return;
    }
    current = ex;
    setBadge('Araç Eksper: analiz ediliyor…', null);
    const res = await send({ type: 'analyze', payload: ex.payload, pagePath: location.pathname });
    if (!res || !res.ok) {
      setBadge('Araç Eksper: ' + ((res && res.message) || 'hata'), null);
      return;
    }
    const d = res.data;
    if (d.beklemede) setBadge('⏳ Analiz bekliyor', null);
    else {
      const [emo, txt] = LABEL[d.etiket] || ['', d.etiket];
      setBadge(`${emo} ${txt} · ${d.skor}/10`, d.etiket);
    }
    if (ex.descEl && d.vurgu && d.vurgu.length) A.applyHighlights(ex.descEl, d.vurgu);
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id) return;
    if (msg.type === 'reanalyze') { run().then(() => sendResponse({ ok: true })); return true; }
    if (msg.type === 'dumpPage') { sendResponse({ ok: true, html: dumpSanitized() }); return; }
  });

  /** Gerçek fixture üretmek için: betikleri çıkarır, telefonları maskeler. Satıcı adı seçicisi bilinmediğinden
   *  dosya paylaşılmadan önce kullanıcı tarafından GÖZDEN GEÇİRİLMELİDİR. */
  function dumpSanitized() {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('script,noscript,iframe,#aracx-badge-host,link[rel=preload],link[rel=prefetch]').forEach((e) => e.remove());
    return A.maskPhones('<!doctype html>\n' + clone.outerHTML);
  }

  send({ type: 'getSettings' }).then((s) => {
    if (s && s.autoAnalyze === false) { setBadge('Araç Eksper: hazır (elle analiz)', null); return; }
    run();
  });
})();
