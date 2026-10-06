/* Arama sonuçları: sayfada ZATEN görünen satırları okur, fiyat rozeti ekler. Siteye ek istek atmaz, başka sayfaya
 * gitmez, ilan açmaz. Satır imzası yoksa (ilan listesi değilse) hemen çıkar. Başlık/bağlantı/konum okunup gönderilmez. */
(function () {
  const A = globalThis.AracX;
  if (!A || A._searchLoaded) return;
  const found = A.extractSearchRows(document);
  if (!found.rows.length) return;       // bu bir ilan listesi değil
  A._searchLoaded = true;

  const send = (msg) => chrome.runtime.sendMessage(msg).catch((e) => ({ ok: false, code: 'extension', message: String(e) }));

  const bar = document.createElement('div');
  bar.className = 'aracx-bar';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'aracx-btn';
  btn.textContent = '🚀 Bu sayfayı eksperle';
  const status = document.createElement('span');
  status.className = 'aracx-status';
  bar.append(btn, status);
  const legal = document.createElement('div');
  legal.className = 'aracx-legal';
  legal.textContent = 'otoXray AI · ' + globalThis.OTOXRAY_DISCLAIMER;
  const table = found.rows[0].rowEl.closest('table') || found.rows[0].rowEl.parentElement;
  table.parentElement.insertBefore(legal, table);
  table.parentElement.insertBefore(bar, legal);

  function clearBadges() {
    document.querySelectorAll('.aracx-badge').forEach((e) => e.remove());
  }

  async function run() {
    const cur = A.extractSearchRows(document);
    if (!cur.rows.length) { status.textContent = 'Bu görünümde okunabilir ilan yok (liste yenileniyor olabilir).'; return; }   // boş liste gönderilmez
    btn.disabled = true;
    status.textContent = `${cur.rows.length} ilan değerlendiriliyor…`;
    const res = await send({ type: 'batch', items: A.rowsToItems(cur.rows), pagePath: location.pathname });
    btn.disabled = false;
    if (!res || !res.ok) { status.textContent = (res && res.message) || 'hata'; return; }
    clearBadges();
    const byId = new Map(cur.rows.map((r) => [r.ilan_no, r]));
    for (const s of res.data.sonuclar) {
      const row = byId.get(s.ilan_no);
      if (!row) continue;
      const b = document.createElement('span');
      b.className = 'aracx-badge aracx-' + s.rozet;
      b.textContent = s.rozet_metin;
      b.title = s.emsal_medyan ? `Emsal medyanı ${s.emsal_medyan.toLocaleString('tr-TR')} TL (n=${s.emsal_n})`
                               : `Emsal sayısı: ${s.emsal_n}`;
      row.priceEl.appendChild(b);
      if (s.km_uyari) {
        const k = document.createElement('span');
        k.className = 'aracx-badge aracx-km';
        k.textContent = `Yıllık ${s.yillik_km.toLocaleString('tr-TR')} km`;
        row.priceEl.appendChild(k);
      }
    }
    status.textContent = `${res.data.sonuclar.length} ilan · yalnız fiyat kıyasıdır, karar değildir` +
      (cur.atlanan.length ? ` · ${cur.atlanan.length} satır okunamadı` : '');
  }

  btn.addEventListener('click', run);

  // Sekme/sıralama değişiminde liste sayfa yenilenmeden değişir: yeni satırlar gelince bir kez yeniden değerlendir.
  // Yalnız satır (TR/TABLE) ekleme/çıkarma izlenir; kendi rozetlerimiz tetiklemez.
  let timer = null;
  new MutationObserver((muts) => {
    const rowChange = muts.some((m) => [...m.addedNodes, ...m.removedNodes].some((n) => n.nodeType === 1 && (n.tagName === 'TR' || n.tagName === 'TABLE' || (n.querySelector && n.querySelector('tr.searchResultsItem')))));
    if (!rowChange) return;
    clearTimeout(timer);
    timer = setTimeout(() => { send({ type: 'getSettings' }).then((s) => { if (s && s.configured && s.autoBatch !== false) run(); }); }, 900);
  }).observe(table.parentElement, { childList: true, subtree: true });
  send({ type: 'getSettings' }).then((s) => { if (s && s.configured && s.autoBatch !== false) run(); });
})();
