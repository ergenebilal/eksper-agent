"""Uçtan uca: otoXray AI eklentisi GERÇEK Chromium'a yüklenir; ilan sayfaları (sentetik fixture) ağ yerine route ile
sunulur; API durumsuz yerel uvicorn'dur. Gerçek siteye HİÇBİR istek gitmez (denetlenir).
Çalıştırma: uv run pytest tests/test_extension_e2e.py   (Chromium: `uv run playwright install chromium`)
Not: Alan adı yalnızca bu testte sayfa yönlendirmesi için sabit olarak geçer."""
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402
import uvicorn  # noqa: E402

from arac_eksper.config.settings import settings  # noqa: E402
from arac_eksper.report.legal import DISCLAIMER  # noqa: E402
from arac_eksper.schemas import DescriptionFindings, Evidence  # noqa: E402
from arac_eksper.web import api as xray_api, xray_app  # noqa: E402

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FX = EXT / "tests" / "fixtures"
TOKEN = "e2e-extension-token-0123456789"
DOMAIN = "sahib" + "inden.com"
SITE = f"https://www.{DOMAIN}"
DETAIL_URL = f"{SITE}/ilan/vasita-otomobil-renault-megane-1234567890/detail"
SEARCH_URL = f"{SITE}/renault-megane"
FEW_URL = f"{SITE}/az-ilan"
BAD_URL = f"{SITE}/ilan/vasita-otomobil-bozuk-9999999999/detail"
REAL_URL = f"{SITE}/ilan/vasita-arazi-suv-pickup-nissan-qashqai-1343960581/detail"
REAL_SEARCH_URL = f"{SITE}/otomobil"          # gerçek (temizlenmiş) arama sayfası: tests/fixtures/real/search_renault.html


class ScriptedLLM:
    """Açıklamadaki gerçek ifadeleri alıntılayan deterministik sahte LLM; gördüğü metni kaydeder."""
    calls = 0
    last_prompt = ""
    delay = 0.0          # yapay LLM gecikmesi (ön hesap testi için)

    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        ScriptedLLM.calls += 1
        ScriptedLLM.last_prompt = user_prompt
        if ScriptedLLM.delay:
            time.sleep(ScriptedLLM.delay)
        from arac_eksper.analysis import belge as bg
        if response_model is bg.TramerBulgular:
            return bg.TramerBulgular(kayitlar=[bg.TramerKayit(tutar=64000, alinti="Kaza: 64.000 TL")], toplam=64000,
                                     toplam_alinti="Toplam: 64.000 TL", agir_hasar="belirsiz")
        return DescriptionFindings(
            sase_direk_podye_islem="belirsiz", airbag="belirsiz", motor_sanziman="belirsiz", km_degisimi_suphesi=False,
            tramer_tutari=0,
            olumlu_sinyaller=[Evidence(etiket="İlk sahibinden", alinti="ilk sahibinden"),
                              Evidence(etiket="Servis bakımlı", alinti="servis bakımlı")],
            olumsuz_sinyaller=[Evidence(etiket="Şase ucu şüphesi", alinti="ŞASE UCU işlemi")],
            belirsiz_ifadeler=[Evidence(etiket="Soru gelirse konuşuruz", alinti="soru gelirse konuşuruz")])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def backend():
    port = free_port()
    old = (settings.extension_token, settings.panel_allowed_hosts)
    settings.extension_token = TOKEN
    settings.panel_allowed_hosts = ["127.0.0.1", "localhost"]
    xray_app.app.dependency_overrides[xray_api.get_llm] = lambda: ScriptedLLM()
    server = uvicorn.Server(uvicorn.Config(xray_app.app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield {"port": port}
    server.should_exit = True
    t.join(timeout=5)
    xray_app.app.dependency_overrides.clear()
    settings.extension_token, settings.panel_allowed_hosts = old


@pytest.fixture(scope="module")
def browser_ctx(backend, tmp_path_factory):
    site_hits = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path_factory.mktemp("profile")), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])

        def route(r):
            url = r.request.url
            host = url.split("/")[2]
            if host.endswith(DOMAIN):
                site_hits.append((url, r.request.service_worker is not None))
                name = {DETAIL_URL: "detail_synthetic.html", SEARCH_URL: "search_synthetic.html",
                        FEW_URL: "search_few_synthetic.html", BAD_URL: "unreadable_synthetic.html",
                        REAL_URL: "detail_realish_synthetic.html"}.get(url.split("?")[0])
                if name:
                    return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=(FX / name).read_text("utf-8"))
                if url.split("?")[0] == REAL_SEARCH_URL and r.request.resource_type == "document":
                    return r.fulfill(status=200, content_type="text/html; charset=utf-8",
                                     body=(ROOT / "tests/fixtures/real/search_renault.html").read_text("utf-8"))
                return r.fulfill(status=404, body="yok")
            if host.startswith("127.0.0.1") or url.startswith("chrome-extension://"):
                return r.continue_()
            return r.abort()
        ctx.route("**/*", route)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=30000)
        ext_id = sw.url.split("/")[2]
        now = int(time.time() * 1000)
        mk = {"groups": {"m:renault megane": {f"L{i}": {"y": 2022, "k": 60000, "f": 900_000 + i * 1000, "t": now, "s": "Megane"}
                                              for i in range(8)}}, "idx": {f"L{i}": "m:renault megane" for i in range(8)}}
        sw.evaluate("s => chrome.storage.local.set(s)", {
            "apiBase": f"http://127.0.0.1:{backend['port']}", "token": TOKEN, "autoAnalyze": True, "autoBatch": True, "mk": mk})
        yield {"ctx": ctx, "sw": sw, "id": ext_id, "hits": site_hits}
        ctx.close()


def session_state(sw):
    return sw.evaluate("async () => await chrome.storage.session.get(null)")


def badge_text(page):
    return page.evaluate("document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent")


@pytest.fixture(scope="module")
def detail_tab(browser_ctx):
    """Sekme açık kalır: kapanınca service worker sonucu (tasarım gereği) temizler."""
    page = browser_ctx["ctx"].new_page()
    page.goto(DETAIL_URL)
    page.wait_for_selector("mark[data-aracx]", timeout=90000)
    yield page
    page.close()


# ------------------------------------------------------------------ detay sayfası
def test_detail_page_highlights_and_sends_only_technical_masked_text(browser_ctx, detail_tab):
    sw, page = browser_ctx["sw"], detail_tab
    marks = {t: k for k, t in page.eval_on_selector_all("mark[data-aracx]", "els => els.map(e => [e.dataset.aracx, e.textContent])")}
    assert marks.get("ŞASE UCU işlemi") == "olumsuz"                        # kırmızı
    assert marks.get("ilk sahibinden") == "olumlu" and marks.get("servis bakımlı") == "olumlu"
    assert marks.get("soru gelirse konuşuruz") == "belirsiz"                 # sarı
    assert "aracx-bad" in page.eval_on_selector("mark[data-aracx=olumsuz]", "e => e.className")

    # güvensiz metin HTML'e dönüşmedi, betik çalışmadı
    assert page.eval_on_selector("#classifiedDescription", "e => e.querySelectorAll('b,img,script').length") == 0
    assert "<b>kalın</b>" in page.inner_text("#classifiedDescription")

    assert "/10" in badge_text(page) and any(x in badge_text(page) for x in ("🟢", "🟡"))

    # KVKK: LLM'e giden metinde satıcı adı/telefonu YOK, telefon maskeli
    sent = ScriptedLLM.last_prompt
    assert "[telefon]" in sent and "0532" not in sent and "Ahmet" not in sent and "111 22 33" not in sent

    st = session_state(sw)
    key = next(k for k in st if k.startswith("r:"))
    data = st[key]["data"]
    assert st[key]["status"] == "ok" and data["etiket"] in ("ALINIR", "DUSUNULEBILIR") and data["tavsiye_teklif"]
    assert data["piyasa"]["n"] >= 5                                          # yerel emsal deposundan geldi
    assert data["yasal_uyari"] == DISCLAIMER


def test_second_visit_uses_local_cache_without_new_llm_call(browser_ctx, detail_tab):
    before = ScriptedLLM.calls
    p2 = browser_ctx["ctx"].new_page()
    p2.goto(DETAIL_URL)
    p2.wait_for_selector("mark[data-aracx]", timeout=60000)
    assert ScriptedLLM.calls == before
    p2.close()


def test_side_panel_renders_card_copies_offer_and_shows_disclaimer(browser_ctx, detail_tab):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    key = next(k for k in session_state(sw) if k.startswith("r:"))
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={key[2:]}")
    panel.wait_for_selector("#verdict", timeout=15000)
    text = panel.text_content("#app")
    for needle in ("Piyasa özeti", "Gizli kusur röntgeni", "Teklif & pazarlık", "Ekspertiz kontrol listesi",
                   "ŞASE UCU işlemi", "Açılış teklifi", "ekspertize götürmeye değer", "Üst sınır (yalnız sana)",
                   "Piyasa ortalaması", "Tipik aralık", "Makul anlaşma noktası", "Nasıl hesaplandı",
                   "Satıcıya sorulacaklar", "Bu araçta özellikle", "Her araçta", "soru gelirse konuşuruz"):
        assert needle in text, needle
    assert panel.text_content("#avg") and "TL" in panel.text_content("#avg")  # piyasa ortalaması kartta
    assert "Piyasa ortalaması (ilan medyanı)" in panel.text_content("#basis")  # hesabın dayanağı açılır kutuda
    assert panel.text_content("#legal").strip() == DISCLAIMER                # altbilgide AYNEN
    assert "otoXray AI" in panel.text_content(".top")
    panel.evaluate("""() => { window.__copied = null; navigator.clipboard.writeText = async (t) => { window.__copied = t; }; }""")
    panel.click("#copy")
    panel.wait_for_function("window.__copied !== null")
    copied = panel.evaluate("window.__copied")
    d = session_state(sw)[key]["data"]
    fmt = lambda n: f"{n:,}".replace(",", ".")
    assert "ekspertiz şartıyla" in copied and f"{fmt(d['tavsiye_teklif'])} TL" in copied
    assert "sag arka camurluk değişen" in copied
    if d["ust_sinir"] != d["tavsiye_teklif"]:
        assert fmt(d["ust_sinir"]) not in copied                              # üst sınır satıcıya gidecek metinde YOK
    panel.close()


def test_unreadable_page_makes_no_verdict_and_no_api_call(browser_ctx):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    calls = ScriptedLLM.calls
    page = ctx.new_page()
    page.goto(BAD_URL)
    page.wait_for_function(
        "document.getElementById('aracx-badge-host') && document.getElementById('aracx-badge-host').shadowRoot"
        ".querySelector('button').textContent.includes('okunamadı')", timeout=30000)
    assert ScriptedLLM.calls == calls
    assert "unreadable" in [v["status"] for v in session_state(sw).values() if isinstance(v, dict) and "status" in v]
    page.close()


# ------------------------------------------------------------------ arama sayfası
def test_search_page_adds_neutral_price_badges_from_local_comparables(browser_ctx):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    page = ctx.new_page()
    page.goto(SEARCH_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=60000)
    rows = page.eval_on_selector_all(
        "tr.searchResultsItem",
        "els => els.map(e => [e.dataset.id, Array.from(e.querySelectorAll('.aracx-badge')).map(b => b.className + '|' + b.textContent)])")
    by = {i: b for i, b in rows}
    assert "aracx-avantajli" in by["1111111111"][0] and "avantajlı" in by["1111111111"][0]
    assert "aracx-piyasada" in by["2222222222"][0]
    assert "aracx-pahali" in by["3333333333"][0] and "Pahalı" in by["3333333333"][0]
    assert "aracx-cok_ucuz_suphe" in by["4444444444"][0] and "nedenini sor" in by["4444444444"][0]
    assert by["9999999990"] == []                                            # okunamayan satır rozetsiz
    assert "aracx-emsal_yetersiz" in by["1313131313"][0]                     # farklı seri (Clio) Megane'lerle KIYASLANMADI
    assert by["1212121212"] == []                                            # iki fiyatlı (eski/yeni) satır belirsiz: atlanır, batch bozulmaz
    assert all("kelepir" not in b.lower() for v in by.values() for b in v)
    assert "karar değildir" in page.inner_text(".aracx-status") and "2 satır okunamadı" in page.inner_text(".aracx-status")
    assert DISCLAIMER in page.text_content(".aracx-legal")                   # arayüzde zorunlu uyarı

    # emsaller yalnızca kullanıcının tarayıcısında (yerel depo) birikti
    mk = sw.evaluate("async () => (await chrome.storage.local.get('mk')).mk")
    assert len(mk["groups"]["p:renault-megane"]) == 9
    assert all(set(r) <= {"y", "k", "f", "t", "s"} for r in mk["groups"]["p:renault-megane"].values())   # başlık/bağlantı yok
    assert {r["s"] for r in mk["groups"]["p:renault-megane"].values()} == {"Megane", "Clio"}
    page.close()


def test_empty_list_is_never_sent_and_list_changes_are_reevaluated(browser_ctx):
    """Gerçek sayfada sekme değişince satırlar boşalıp yeniden doluyor: boş liste sunucuya gitmemeli (422),
    yeni satırlar gelince otomatik yeniden değerlendirilmeli."""
    page = browser_ctx["ctx"].new_page()
    page.goto(SEARCH_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=60000)
    page.evaluate("""() => { window.__saved = document.querySelector('tbody').innerHTML; document.querySelector('tbody').replaceChildren(); }""")
    page.click(".aracx-btn")
    page.wait_for_function("document.getElementById('aracx-bar-host').shadowRoot.querySelector('.aracx-status').textContent.includes('okunabilir ilan yok')", timeout=15000)
    assert "reddetti" not in page.inner_text(".aracx-status")
    page.evaluate("() => { document.querySelector('tbody').innerHTML = window.__saved; }")      # liste yeniden dolar
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=30000)   # kendiliğinden
    page.close()


def test_corrupt_local_comparables_are_ignored_not_sent(browser_ctx):
    """Önceki hatalı sürümden depoda kalmış milyarlık fiyatlı kayıt, istek reddettirmemeli."""
    sw = browser_ctx["sw"]
    sw.evaluate("""async () => { const now = Date.now();
        await chrome.storage.local.set({mk: {groups: {'p:az-ilan': {BAD1: {y: 2022, k: 1, f: 12501150000, t: now}, 'ok_1': {y: 2022, k: 1, f: 500000, t: now}}}, idx: {}}}); }""")
    page = browser_ctx["ctx"].new_page()
    page.goto(FEW_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 3", timeout=60000)
    assert "reddetti" not in page.inner_text(".aracx-status")
    mk = sw.evaluate("async () => (await chrome.storage.local.get('mk')).mk")
    assert "BAD1" not in mk["groups"]["p:az-ilan"]
    page.close()


def test_few_rows_say_comparables_are_insufficient(browser_ctx):
    page = browser_ctx["ctx"].new_page()
    page.goto(FEW_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 3", timeout=60000)
    classes = page.eval_on_selector_all(".aracx-badge", "els => els.map(e => e.className + '|' + e.textContent)")
    assert all("aracx-emsal_yetersiz" in c and "Benzer ilan az" in c for c in classes)
    page.close()


def test_options_page_shows_disclaimer_and_wipe_clears_local_data(browser_ctx):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    page = ctx.new_page()
    page.goto(f"chrome-extension://{browser_ctx['id']}/options/options.html")
    page.wait_for_selector("#legal")
    page.wait_for_function("document.getElementById('legal').textContent.length > 20")
    assert page.text_content("#legal").strip() == DISCLAIMER and "otoXray AI" in page.title()
    page.click("#wipe")
    page.wait_for_function("document.getElementById('msg').textContent.includes('silindi')")
    left = sw.evaluate("async () => Object.keys(await chrome.storage.local.get(null)).filter(k => k === 'mk' || k.startsWith('ac:'))")
    assert left == []
    page.close()


def test_label_driven_reading_on_a_realistic_layout_and_diagnose_report(browser_ctx):
    """Yıl/km yalnız özet çubuğunda, özellikler tablo satırında: etiket metnine dayalı okuma çalışmalı.
    Satıcı kutusu (ad/telefon) okunmaz; teşhis raporu yalnız yapı içerir."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    page = ctx.new_page()
    page.goto(REAL_URL)
    page.wait_for_selector("mark[data-aracx]", timeout=60000)
    st = session_state(sw)
    key = next(k for k, v in st.items() if v.get("meta", {}).get("ilan_no") == "1343960581")
    meta = st[key]["meta"]
    assert (meta["fiyat"], meta["yil"], meta["km"]) == (1_270_000, 2014, 159_000)
    assert st[key]["status"] == "ok"
    sent = ScriptedLLM.last_prompt
    assert "Nuri" not in sent and "378" not in sent and "[telefon]" in sent
    assert "Sahibinden" not in sent                                          # 'Kimden' (satıcı türü) okunmadı
    # filtre kutusundaki uzun "Marka" listesi değer sanılmadı (gerçek hata: marka 60 karakteri aşıp 422 verdi)
    assert "Audi BMW" not in str(st[key]) and st[key]["status"] == "ok"

    rep = sw.evaluate("async (id) => await chrome.tabs.sendMessage(id, {type: 'diagnose'})", int(key[2:]))
    assert rep["ok"] and rep["report"]["okuma"]["ok"] is True
    flat = str(rep["report"])
    assert "Nuri" not in flat and "378" not in flat and "543" not in flat
    assert rep["report"]["etiketler"]["İlan No"] != "bulunamadi" and rep["report"]["fiyat"] != "bulunamadi"
    page.close()


def test_rejected_input_names_the_field_but_never_echoes_the_value(browser_ctx):
    sw = browser_ctx["sw"]
    secret = "GIZLI-ILAN-METNI-" + "x" * 20
    res = sw.evaluate("async (b) => await api('/api/v1/analyze', {body: b})",
                      {"ilan_no": "1", "baslik": secret, "fiyat": -5, "yil": 2022, "km": 1})
    assert res["ok"] is False and res["code"] == "invalid"
    assert "fiyat" in res["message"] and "GIZLI" not in res["message"]


def test_no_market_card_is_honest_and_still_offers_a_labelled_price(browser_ctx):
    """Emsal yokken piyasa fiyatı UYDURULMAZ; teklif yalnız ilan fiyatından, uyarıyla gösterilir."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    sw.evaluate("""async () => { const all = await chrome.storage.local.get(null);
        await chrome.storage.local.remove(Object.keys(all).filter(k => k === 'mk' || k.startsWith('ac:'))); }""")
    page = ctx.new_page()
    page.goto(REAL_URL)
    page.wait_for_selector("mark[data-aracx]", timeout=60000)
    st = session_state(sw)
    key = next(k for k, v in st.items() if v.get("meta", {}).get("ilan_no") == "1343960581")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={key[2:]}")
    panel.wait_for_selector("#offer", timeout=15000)
    assert panel.locator("#no-market").count() == 1 and panel.locator("#avg").count() == 0
    assert "tahmin edilmez" in panel.text_content("#no-market")
    offer = panel.text_content("#offer")
    assert "Açılış teklifi" in offer and "yalnızca ilan fiyatı" in offer
    panel.close()
    page.close()


def test_instant_pre_calculation_is_shown_while_the_llm_is_still_working(browser_ctx):
    """LLM yavaşken (burada 6 sn) piyasa + teklif ön hesabı ANINDA görünür; röntgen bitince tam karne gelir."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    now = int(time.time() * 1000)
    mk = {"groups": {"m:nissan qashqai": {f"Q{i}": {"y": 2014, "k": 159000 + i * 500, "f": 1_200_000 + i * 2000, "t": now,
                                                    "s": "Qashqai"} for i in range(6)}}, "idx": {}}
    sw.evaluate("""async (mk) => { const all = await chrome.storage.local.get(null);
        await chrome.storage.local.remove(Object.keys(all).filter(k => k.startsWith('ac:')));
        await chrome.storage.local.set({mk}); }""", mk)
    ScriptedLLM.delay = 6.0
    try:
        page = ctx.new_page()
        page.goto(REAL_URL)
        key = None
        deadline = time.time() + 5
        while time.time() < deadline and key is None:      # LLM bitmeden (6 sn) 'loading + quick' görünmeli
            for k, v in session_state(sw).items():
                if v.get("meta", {}).get("ilan_no") == "1343960581" and v.get("status") == "loading" and v.get("quick"):
                    key = k
            time.sleep(0.2)
        assert key, "ön hesap LLM bitmeden gelmedi"
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={key[2:]}")
        panel.wait_for_selector("#waiting", timeout=10000)
        text = panel.text_content("#app")
        assert "Açıklama röntgeni yapılıyor" in text and "Piyasa ortalaması" in text and "ön hesap" in text.lower()
        assert panel.locator("#verdict").count() == 0                    # henüz etiket YOK
        panel.wait_for_selector("#verdict", timeout=40000)               # LLM bitince tam karne
        assert panel.locator("#waiting").count() == 0
        panel.close()
        page.close()
    finally:
        ScriptedLLM.delay = 0.0


def test_outdated_server_is_reported_not_silently_ignored(browser_ctx):
    """Eski sunucuda /quick yok (404): panel 'ön hesap hazır' demeye devam etmemeli, nedenini söylemeli."""
    sw = browser_ctx["sw"]
    res = sw.evaluate("async () => await api('/api/v1/yok-boyle-bir-uc', {body: {}})")
    assert res["ok"] is False and res["code"] == "outdated" and "yeniden başlatın" in res["message"]


def test_extension_never_requests_the_site_by_itself(browser_ctx):
    """Siteye giden her istek test sayfalarının kendi gezintisidir; service worker/eklenti hiç istek atmaz."""
    hits = browser_ctx["hits"]
    assert hits, "test sayfaları yüklenmedi"
    assert all(not from_sw for _, from_sw in hits)
    allowed = {DETAIL_URL, SEARCH_URL, FEW_URL, BAD_URL, REAL_URL, REAL_SEARCH_URL}
    stray = [u for u, _ in hits if u.split("?")[0] not in allowed and not u.endswith("favicon.ico")]
    assert stray == [], f"beklenmeyen istek: {stray}"


def test_wrong_token_is_reported_not_crashing(browser_ctx):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    sw.evaluate("""async () => { const all = await chrome.storage.local.get(null);
        await chrome.storage.local.remove(Object.keys(all).filter(k => k.startsWith('ac:')));   // önbellek yanıtı gizlemesin
        await chrome.storage.local.set({token: 'yanlis-yanlis-yanlis-yanlis'}); }""")
    page = ctx.new_page()
    page.goto(DETAIL_URL + "?x=1")
    page.wait_for_function(
        "document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent.includes('reddedildi')",
        timeout=30000)
    page.close()
    sw.evaluate("t => chrome.storage.local.set({token: t})", TOKEN)


def test_invited_user_sees_quota_and_sends_feedback_without_description(browser_ctx):
    from arac_eksper.web import accounts
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    uid = accounts.create_member("e2e@ornek.com", gunluk_kota=7)
    key = accounts.issue_key(uid)
    sw.evaluate("""async (k) => { const all = await chrome.storage.local.get(null);
        await chrome.storage.local.remove(Object.keys(all).filter(x => x.startsWith('ac:')));
        await chrome.storage.local.set({token: k}); }""", key)
    try:
        page = ctx.new_page()
        page.goto(DETAIL_URL + "?fb=1")
        page.wait_for_selector("mark[data-aracx]", timeout=90000)
        k = next(x for x, v in session_state(sw).items() if x.startswith("r:") and v.get("status") == "ok"
                 and v["data"].get("kota"))
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={k[2:]}")
        panel.wait_for_selector("#feedback", timeout=15000)
        assert "Bugünkü analiz hakkın: 6/7" in panel.text_content("#app")
        panel.click("#fb-send")                                          # boş gönderim reddedilir
        assert "Önce" in panel.text_content("#feedback")
        panel.click("#feedback button:has-text('👍')")
        panel.select_option("#fb-sonuc", "ekspertiz_temiz")
        panel.fill("#fb-not", "Doğru çıktı, satıcı 0532 111 22 33")
        panel.click("#fb-send")
        panel.wait_for_selector("#feedback >> text=Teşekkürler", timeout=15000)
        fb = accounts.list_feedback()[0]
        assert fb["member_id"] == uid and fb["oy"] == "pos" and fb["sonuc"] == "ekspertiz_temiz"
        assert fb["ilan_no"] == "1234567890" and "0532" not in fb["notu"]
        panel.close()
        page.close()
    finally:
        sw.evaluate("t => chrome.storage.local.set({token: t})", TOKEN)


def test_email_code_login_and_logout_on_options_page(browser_ctx, monkeypatch):
    import re as _re
    from arac_eksper.web import accounts, mailer
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "otoxray@cybergene.co")
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, html=None: sent.append(subject))
    accounts.create_member("giris@ornek.com", gunluk_kota=9, aylik_kota=90, bitis="2099-12-31")
    sw.evaluate("() => chrome.storage.local.remove(['token', 'email'])")
    try:
        page = ctx.new_page()
        page.goto(f"chrome-extension://{browser_ctx['id']}/options/options.html")
        assert page.is_hidden("#code-form") and page.is_hidden("#signed-in")
        page.fill("#email", "giris@ornek.com")
        page.click("#send-code")
        page.wait_for_selector("#code-form:not([hidden])", timeout=15000)
        code = _re.search(r"(\d{6})", sent[-1]).group(1)
        page.fill("#code", code)
        page.click("#login")
        page.wait_for_selector("#signed-in:not([hidden])", timeout=15000)
        page.wait_for_selector("#rights dd", timeout=15000)
        text = page.text_content("#signed-in")
        assert "giris@ornek.com" in text and "9 / 9" in text and "90 / 90" in text
        stored = sw.evaluate("async () => await chrome.storage.local.get(['token', 'email'])")
        assert stored["email"] == "giris@ornek.com" and stored["token"].startswith("oxr_")
        assert "oxr_" not in page.content()                      # anahtar sayfaya hiç verilmez
        page.click("#logout")
        page.wait_for_selector("#signed-out:not([hidden])", timeout=15000)
        assert accounts.find_by_key(stored["token"]) is None     # sunucuda da iptal
        page.close()
    finally:
        sw.evaluate("t => chrome.storage.local.set({token: t, email: ''})", TOKEN)


def test_opening_a_listing_spends_nothing_until_the_xray_button(browser_ctx):
    from arac_eksper.web import accounts
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    uid = accounts.create_member("onizleme@ornek.com", gunluk_kota=5)
    key = accounts.issue_key(uid)
    sw.evaluate("""async (k) => { const all = await chrome.storage.local.get(null);
        await chrome.storage.local.remove(Object.keys(all).filter(x => x.startsWith('ac:')));
        await chrome.storage.local.set({token: k, autoAnalyze: false}); }""", key)
    try:
        calls = ScriptedLLM.calls
        page = ctx.new_page()
        page.goto(DETAIL_URL + "?onizleme=1")
        page.wait_for_function(
            "document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent.includes('ön hesap')",
            timeout=30000)
        assert ScriptedLLM.calls == calls and accounts.used_today(uid) == 0          # ilan açmak: LLM yok, hak yok
        k = next(x for x, v in session_state(sw).items() if x.startswith("r:") and v.get("status") == "preview")
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={k[2:]}")
        panel.wait_for_selector("#xray-cta", timeout=15000)
        assert "1 analiz hakkı kullanır. Bugün kalan: 5/5" in panel.text_content("#xray-note")
        assert panel.is_visible("#market")
        panel.click("#run-xray")
        panel.wait_for_selector("#verdict", timeout=60000)
        assert ScriptedLLM.calls > calls and accounts.used_today(uid) == 1
        panel.close()
        page.close()
    finally:
        sw.evaluate("t => chrome.storage.local.set({token: t, autoAnalyze: true})", TOKEN)



BAR = "document.getElementById('aracx-bar-host')"


def test_real_search_page_badges_rows_and_groups_by_series(browser_ctx):
    """Gerçek arama sayfası: reklam satırı 'okunamadı' sayılmaz; emsaller marka+seri grubuna yazılır (yol değil)."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    page = ctx.new_page()
    page.goto(REAL_SEARCH_URL + "?query_text=renault")
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 15", timeout=60000)
    st = page.inner_text(".aracx-status")
    assert "21 ilan" in st and "okunamadı" not in st
    assert page.eval_on_selector_all("tr.nativeAd .aracx-badge", "e => e.length") == 0
    groups = sw.evaluate("async () => Object.keys((await chrome.storage.local.get('mk')).mk.groups)")
    assert "m:renault megane" in groups and "m:renault clio" in groups and "p:otomobil" not in groups
    page.close()


def test_bar_survives_site_replacing_the_table_and_new_rows_get_badges(browser_ctx):
    """Site sayfa geçişini yenilemeden yapıp tabloyu kapsayıcısıyla değiştirince çubuk geri gelir, yeni satırlar değerlendirilir."""
    page = browser_ctx["ctx"].new_page()
    page.goto(SEARCH_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=60000)
    page.evaluate("""() => {
        const t = document.querySelector('table'); const box = t.parentElement;
        const clone = box.cloneNode(true);                          // "2. sayfa": aynı yapı, farklı ilan numaraları
        clone.querySelectorAll('.aracx-badge').forEach(b => b.remove());
        clone.querySelectorAll('#aracx-bar-host').forEach(b => b.remove());
        clone.querySelectorAll('tr.searchResultsItem').forEach((tr, i) => {
            const id = tr.getAttribute('data-id'); if (!id) return;
            const nid = String(5000000000 + i); tr.setAttribute('data-id', nid);
            tr.querySelectorAll('a').forEach(a => a.setAttribute('href', (a.getAttribute('href') || '').replace(id, nid)));
        });
        box.replaceWith(clone); }""")
    page.wait_for_function(BAR + " && " + BAR + ".isConnected", timeout=15000)
    page.wait_for_function("document.querySelectorAll('tr[data-id^=\"5000000\"] .aracx-badge').length >= 7", timeout=30000)
    page.close()


def test_bar_comes_back_after_back_forward_cache(browser_ctx):
    page = browser_ctx["ctx"].new_page()
    page.goto(SEARCH_URL)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=60000)
    page.evaluate("() => { document.getElementById('aracx-bar-host').remove(); document.querySelectorAll('.aracx-badge').forEach(b => b.remove());"
                  " window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true})); }")
    page.wait_for_function(BAR + " && " + BAR + ".isConnected", timeout=15000)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 9", timeout=30000)
    page.close()


def test_war_room_pool_and_compare(browser_ctx):
    """R3: iki ilan havuza eklenir, seçilir, karşılaştırılır; havuz yalnız yerel depoda, en fazla 10 ilan."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    sw.evaluate("() => chrome.storage.local.remove('havuz')")
    panels = []
    for url in (DETAIL_URL + "?havuz=1", REAL_URL + "?havuz=1"):
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_selector("#aracx-badge-host", state="attached", timeout=90000)
        page.wait_for_function("document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent.includes('/10')", timeout=90000)
        no = "1234567890" if url.startswith(DETAIL_URL) else "1343960581"
        tab_id = next(k[2:] for k, v in session_state(sw).items()
                      if k.startswith("r:") and (v.get("meta") or {}).get("ilan_no") == no and v.get("status") == "ok")
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={tab_id}")
        panel.wait_for_selector("#havuz-add", timeout=15000)
        panel.click("#havuz-add")
        panel.wait_for_selector("#havuz-add.pooled", timeout=15000)
        panels.append((page, panel))
    havuz = sw.evaluate("async () => (await chrome.storage.local.get('havuz')).havuz")
    assert len(havuz["items"]) == 2 and all(it["sonuc"] for it in havuz["items"].values())
    assert all(it["url"].startswith("https://") for it in havuz["items"].values())
    panel = panels[-1][1]
    panel.click("#tab-havuz")
    panel.wait_for_selector("#havuz-list .havuz-item", timeout=15000)
    for i in range(2):                                   # her işaretlemede panel yeniden çizilir: locator yeniden bulur
        panel.locator(".havuz-item input[type=checkbox]").nth(i).check()
    assert panel.is_enabled("#compare-btn")
    panel.click("#compare-btn")
    panel.wait_for_selector("#compare-result", timeout=60000)
    txt = panel.text_content("#compare-result")
    assert "Fiyat/performans galibi" in txt and "En riskli" in txt and "Pazarlık şansı en yüksek" in txt
    son = sw.evaluate("async () => (await chrome.storage.local.get('havuz')).havuz.son")
    assert len(son["ids"]) == 2 and son["data"]["galip"] in son["ids"]
    panel.locator(".havuz-item select.durum").nth(0).select_option("ekspertiz_temiz")      # R5.3 gerçek sonuç
    panel.wait_for_function("async () => Object.values((await chrome.storage.local.get('havuz')).havuz.items).some((it) => it.durum === 'ekspertiz_temiz')", timeout=15000)
    for page, p in panels:
        p.close(); page.close()
    sw.evaluate("() => chrome.storage.local.remove('havuz')")


def test_document_xray_tramer_paste(browser_ctx):
    """R5.1/R5.4: panelde hasar kaydı metni yapıştırılır → ilanla karşılaştırma ve üst sınır önerisi; belge sonucu sekmeye özel."""
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    page = ctx.new_page()
    page.goto(DETAIL_URL + "?belge=1")
    page.wait_for_selector("#aracx-badge-host", state="attached", timeout=90000)
    page.wait_for_function("document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent.includes('/10')", timeout=90000)
    tab_id = next(k[2:] for k, v in session_state(sw).items()
                  if k.startswith("r:") and (v.get("meta") or {}).get("ilan_no") == "1234567890" and v.get("status") == "ok")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={tab_id}")
    panel.wait_for_selector("#belge", timeout=15000)
    panel.click("#belge .seg button[data-tur=tramer]")
    panel.fill("#belge-metin", "Hasar kaydi sorgusu\nKaza: 64.000 TL\nToplam: 64.000 TL\nSorgu tarihi 2026")
    panel.click("#belge-go")
    panel.wait_for_selector("#belge-sonuc", timeout=60000)
    txt = panel.text_content("#belge-sonuc")
    assert "Hasar kaydı" in txt and "64.000" in txt
    panel.close(); page.close()
