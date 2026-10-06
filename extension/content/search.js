/* Arama sonuçları: sayfada ZATEN görünen satırları okur, fiyat rozeti ekler. Siteye ek istek atmaz, başka sayfaya
 * gitmez, ilan açmaz. Başlık/bağlantı/konum okunup gönderilmez.
 *
 * Kalıcılık: site sayfa geçişini/sıralamayı sayfa yenilemeden yapabilir ve tabloyu (kapsayıcısıyla) değiştirebilir;
 * geri dönüşte sayfa önbellekten gelebilir. Bu yüzden çubuk "bir kez kur" değil, tek bir belge gözlemcisiyle "tablo
 * göründükçe yerinde tut" mantığıyla çalışır; satır kümesi değişince rozetler yeniden hesaplanır.
 * Görünüm: CyberGene; çubuk shadow DOM içinde (sitenin CSS'i bozamaz, biz de sitenin stilini bozmayız). */
(function () {
  const A = globalThis.AracX;
  if (!A || A._searchLoaded) return;
  A._searchLoaded = true;

  const send = (msg) => chrome.runtime.sendMessage(msg).catch((e) => ({ ok: false, code: 'extension', message: String(e) }));
  const RETRY_MS = 30000;          // aynı liste için hata sonrası kendiliğinden yeniden deneme aralığı

  // ------------------------------------------------------------------ çubuk (shadow DOM, sabit şablon)
  const host = document.createElement('div');
  host.id = 'aracx-bar-host';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
<style>
  :host{all:initial;display:block;margin:10px 0 12px}
  .bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:10px 12px 10px 14px;border-radius:16px;
    background:radial-gradient(260px 120px at 0% 0%,rgba(168,85,247,.22),transparent 70%),#0a0d14;
    border:1px solid rgba(255,255,255,.08);box-shadow:0 10px 30px rgba(7,9,14,.18);
    font:13px/1.4 "oxr-inter",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:#f4f4f6}
  .brand{display:flex;align-items:center;gap:9px;min-width:0}
  .brand img{width:26px;height:26px;flex:none;border-radius:7px}
  .brand b{display:block;font:600 14px/1.1 "oxr-grotesk","Space Grotesk",system-ui,sans-serif;letter-spacing:-.02em}
  .brand small{display:block;font-size:10.5px;color:#989ba9;letter-spacing:.03em}
  button{all:unset;box-sizing:border-box;display:inline-flex;align-items:center;gap:8px;cursor:pointer;
    padding:9px 16px;border-radius:12px;font:600 13px/1 "oxr-inter",Inter,system-ui,sans-serif;color:#fff;
    background:radial-gradient(at 0 0,rgba(236,72,153,.33),transparent 65%),linear-gradient(120deg,#5d34d0,#7547dc 65%,#3b82f6);
    box-shadow:0 8px 20px rgba(93,52,208,.30),inset 0 1px 0 rgba(255,255,255,.25);transition:transform .14s,box-shadow .14s}
  button:hover{transform:translateY(-1px);box-shadow:0 12px 26px rgba(93,52,208,.38),inset 0 1px 0 rgba(255,255,255,.25)}
  button:focus-visible{outline:2px solid #a855f7;outline-offset:2px}
  button[disabled]{opacity:.7;cursor:progress;transform:none}
  .scan{width:14px;height:14px;flex:none}
  .status{flex:1 1 220px;min-width:0;color:#c2c1cf}
  .status b{color:#f4f4f6;font-weight:600}
  .legal{flex-basis:100%;font-size:11px;line-height:1.4;color:#6b6e80;border-top:1px solid rgba(185,192,224,.13);padding-top:7px;margin-top:-2px}
  @media (prefers-reduced-motion:reduce){button{transition:none}}
</style>
<div class="bar" part="bar">
  <span class="brand"><img alt=""><span><b>otoXray AI</b><small>CyberGene</small></span></span>
  <button type="button" class="aracx-btn"><svg class="scan" viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="1.5" y="1.5" width="13" height="13" rx="3.5" stroke="currentColor" stroke-width="1.5"/><path d="M4 8h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg><span>Bu sayfayı eksperle</span></button>
  <span class="status aracx-status" role="status"></span>
  <div class="legal aracx-legal"></div>
</div>`;
  root.querySelector('img').src = chrome.runtime.getURL('icons/cg.svg');
  const btn = root.querySelector('button'), label = btn.querySelector('span');
  const status = root.querySelector('.status');
  root.querySelector('.legal').textContent = globalThis.OTOXRAY_DISCLAIMER;

  function say(text, strong) {
    status.replaceChildren();
    if (strong) { const b = document.createElement('b'); b.textContent = strong; status.append(b, ' '); }
    status.append(text);
  }

  // ------------------------------------------------------------------ yerinde tutma
  function ensureBar(rows) {
    const table = rows[0].rowEl.closest('table') || rows[0].rowEl.parentElement;
    if (host.isConnected && host.nextElementSibling === table) return;
    table.parentElement.insertBefore(host, table);
  }

  function clearBadges() { document.querySelectorAll('.aracx-badge').forEach((e) => e.remove()); }

  let busy = false, lastSig = '', lastFailSig = '', lastFailAt = 0;
  const sigOf = (rows) => rows.map((r) => r.ilan_no).join(',');

  async function run() {
    const cur = A.extractSearchRows(document);
    if (!cur.rows.length) { say('Bu görünümde okunabilir ilan yok (liste yenileniyor olabilir).'); return; }   // boş liste gönderilmez
    ensureBar(cur.rows);
    busy = true; btn.disabled = true; label.textContent = 'Kıyaslanıyor…';
    say(`${cur.rows.length} ilan değerlendiriliyor…`);
    const sig = sigOf(cur.rows);
    const res = await send({ type: 'batch', items: A.rowsToItems(cur.rows), pagePath: location.pathname });
    busy = false; btn.disabled = false; label.textContent = 'Yeniden eksperle';
    if (!res || !res.ok) { lastFailSig = sig; lastFailAt = Date.now(); say((res && res.message) || 'Bir hata oluştu.'); return; }
    lastSig = sig;
    clearBadges();
    const byId = new Map(cur.rows.map((r) => [r.ilan_no, r]));
    for (const s of res.data.sonuclar) {
      const row = byId.get(s.ilan_no);
      if (!row || !row.priceEl.isConnected) continue;
      const b = document.createElement('span');
      b.className = 'aracx-badge aracx-' + s.rozet;
      b.textContent = s.rozet_metin;
      b.title = s.rozet === 'emsal_yetersiz'
        ? `Kıyas için aynı seri, yakın yıl ve km'de en az 5 benzer ilan gerekir (şu an ${s.emsal_n}). Aynı modelin diğer arama sayfalarını gezdikçe artar.`
        : s.emsal_medyan ? `Emsal medyanı ${s.emsal_medyan.toLocaleString('tr-TR')} TL (n=${s.emsal_n})`
                         : `Emsal sayısı: ${s.emsal_n}`;
      row.priceEl.appendChild(b);
      if (s.km_uyari) {
        const k = document.createElement('span');
        k.className = 'aracx-badge aracx-km';
        k.textContent = `Yıllık ${s.yillik_km.toLocaleString('tr-TR')} km`;
        row.priceEl.appendChild(k);
      }
    }
    say(`· yalnız fiyat kıyasıdır, karar değildir` + (cur.atlanan.length ? ` · ${cur.atlanan.length} satır okunamadı` : ''),
        `${res.data.sonuclar.length} ilan`);
  }

  btn.addEventListener('click', run);

  let settings = null;
  const auto = () => settings && settings.configured && settings.autoBatch !== false;

  function tick() {
    const cur = A.extractSearchRows(document);
    if (!cur.rows.length) return;                 // tablo yok/boş: çubuk olduğu yerde kalır, boş liste gönderilmez
    ensureBar(cur.rows);
    if (busy || !auto()) return;
    const sig = sigOf(cur.rows);
    const unbadged = cur.rows.some((r) => !r.priceEl.querySelector('.aracx-badge'));
    if (sig === lastFailSig && Date.now() - lastFailAt < RETRY_MS) return;   // hata sonrası aynı listeyi sürekli deneme
    if (sig !== lastSig || unbadged) run();
  }

  // Tek belge gözlemcisi: tablo/satır eklenip çıkınca (sayfa geçişi, sıralama, kapsayıcı değişimi) kısa gecikmeyle tick.
  // Kendi rozetlerimiz (span.aracx-badge) tetiklemez; çubuk shadow DOM'da olduğundan içi gözlemciye görünmez.
  let timer = null;
  const ours = (n) => n.nodeType !== 1 || n.id === 'aracx-bar-host' || (n.classList && n.classList.contains('aracx-badge'));
  new MutationObserver((muts) => {
    if (!muts.some((m) => [...m.addedNodes, ...m.removedNodes].some((n) => !ours(n)))) return;
    clearTimeout(timer);
    timer = setTimeout(tick, 600);
  }).observe(document.documentElement, { childList: true, subtree: true });
  // Geri/ileri: sayfa önbellekten dönerse betik yeniden çalışmaz → yeniden kur ve değerlendir
  window.addEventListener('pageshow', (e) => { if (e.persisted) { lastSig = ''; tick(); } });
  window.addEventListener('popstate', () => { lastSig = ''; setTimeout(tick, 300); });

  send({ type: 'getSettings' }).then((s) => { settings = s; tick(); });
})();
