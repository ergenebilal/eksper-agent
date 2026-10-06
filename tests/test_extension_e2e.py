"""Uçtan uca: eklenti GERÇEK Chromium'a yüklenir, sahte sahibinden sayfaları (sentetik fixture) ağ yerine
route ile sunulur, API yerel uvicorn'dur. Gerçek sahibinden'e HİÇBİR istek gitmez (denetlenir).
Çalıştırma: uv run pytest tests/test_extension_e2e.py -m e2e   (Chromium: `uv run playwright install chromium`)"""
import socket
import threading
import time
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from arac_eksper.config.settings import settings  # noqa: E402
from arac_eksper.schemas import DescriptionFindings, Evidence, ListingSummary  # noqa: E402
from arac_eksper.storage import repo  # noqa: E402
from arac_eksper.storage.db import Base  # noqa: E402
from arac_eksper.storage.models import Listing, Verdict  # noqa: E402
from arac_eksper.web import api as ext_api, app as webapp  # noqa: E402

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FX = EXT / "tests" / "fixtures"
TOKEN = "e2e-extension-token-0123456789"
DETAIL_URL = "https://www.sahibinden.com/ilan/vasita-otomobil-renault-megane-1234567890/detail"
SEARCH_URL = "https://www.sahibinden.com/renault-megane"
BAD_URL = "https://www.sahibinden.com/ilan/vasita-otomobil-bozuk-9999999999/detail"


class ScriptedLLM:
    """Açıklamadaki gerçek ifadeleri alıntılayan deterministik sahte LLM."""
    calls = 0

    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        ScriptedLLM.calls += 1
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
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    for i in range(8):   # soğuk başlangıç olmasın: 8 emsal (~903k)
        repo.create_or_update_listing_summary(
            db, ListingSummary(ilan_no=f"M{i}", url="", baslik=f"Renault Megane {i}", fiyat=900_000 + i * 1000, yil=2022,
                               km=60000, il="Bursa", ilan_tarihi=date.today()), "Renault", "Megane")
    old = (settings.extension_token, settings.panel_allowed_hosts, settings.panel_token)
    settings.extension_token = TOKEN
    settings.panel_token = "p" * 24      # panel de token olmadan başlamaz (kasıtlı)
    settings.panel_allowed_hosts = ["127.0.0.1", "localhost"]
    webapp.app.dependency_overrides[webapp.get_db] = lambda: Session()
    webapp.app.dependency_overrides[ext_api.get_llm] = lambda: ScriptedLLM()
    server = uvicorn.Server(uvicorn.Config(webapp.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield {"port": port, "db": Session}
    server.should_exit = True
    t.join(timeout=5)
    webapp.app.dependency_overrides.clear()
    settings.extension_token, settings.panel_allowed_hosts, settings.panel_token = old


@pytest.fixture(scope="module")
def browser_ctx(backend, tmp_path_factory):
    sahibinden_hits = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path_factory.mktemp("profile")), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])

        def route(r):
            url = r.request.url
            host = url.split("/")[2]
            if host.endswith("sahibinden.com"):
                sahibinden_hits.append((url, r.request.service_worker is not None))
                name = {DETAIL_URL: "detail_synthetic.html", SEARCH_URL: "search_synthetic.html",
                        BAD_URL: "unreadable_synthetic.html"}.get(url.split("?")[0])
                if name:
                    return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=(FX / name).read_text("utf-8"))
                return r.fulfill(status=404, body="yok")
            if host.startswith("127.0.0.1") or url.startswith("chrome-extension://"):
                return r.continue_()
            return r.abort()
        ctx.route("**/*", route)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=30000)
        ext_id = sw.url.split("/")[2]
        sw.evaluate("s => chrome.storage.local.set(s)", {
            "apiBase": f"http://127.0.0.1:{backend['port']}", "token": TOKEN, "autoAnalyze": True, "autoBatch": True})
        yield {"ctx": ctx, "sw": sw, "id": ext_id, "hits": sahibinden_hits}
        ctx.close()


def session_state(sw):
    return sw.evaluate("async () => await chrome.storage.session.get(null)")


# ------------------------------------------------------------------ detay sayfası
@pytest.fixture(scope="module")
def detail_tab(browser_ctx):
    """Sekme açık kalır: kapanınca service worker sonucu (tasarım gereği) temizler."""
    page = browser_ctx["ctx"].new_page()
    page.goto(DETAIL_URL)
    page.wait_for_selector("mark[data-aracx]", timeout=90000)
    yield page
    page.close()


def test_detail_page_highlights_and_stores_verdict(browser_ctx, backend, detail_tab):
    sw, page = browser_ctx["sw"], detail_tab

    marks = page.eval_on_selector_all("mark[data-aracx]", "els => els.map(e => [e.dataset.aracx, e.textContent])")
    got = {t: k for k, t in marks}
    assert got.get("ŞASE UCU işlemi") == "olumsuz"                       # kırmızı
    assert got.get("ilk sahibinden") == "olumlu" and got.get("servis bakımlı") == "olumlu"
    assert got.get("soru gelirse konuşuruz") == "belirsiz"                  # sarı
    cls = page.eval_on_selector("mark[data-aracx=olumsuz]", "e => e.className")
    assert "aracx-bad" in cls

    # güvensiz metin: HTML'e dönüşmedi, betik çalışmadı
    assert page.eval_on_selector("#classifiedDescription", "e => e.querySelectorAll('b,img,script').length") == 0
    assert "<b>kalın</b>" in page.inner_text("#classifiedDescription")

    badge = page.evaluate("document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent")
    assert "/10" in badge and any(x in badge for x in ("🟢", "🟡"))

    st = session_state(sw)
    key = next(k for k in st if k.startswith("r:"))
    data = st[key]["data"]
    assert st[key]["status"] == "ok" and data["etiket"] in ("ALINIR", "DUSUNULEBILIR") and data["tavsiye_teklif"]
    assert "[telefon]" in str(backend["db"]().query(Verdict).first().detail_json)           # telefon sunucuya maskeli gitti
    assert "0532" not in str(backend["db"]().query(Verdict).first().detail_json)
    assert "Ahmet" not in str(backend["db"]().query(Verdict).first().detail_json)           # satıcı adı okunmadı


def test_side_panel_renders_card_and_copies_offer(browser_ctx, detail_tab):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    key = next(k for k in session_state(sw) if k.startswith("r:"))
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{browser_ctx['id']}/sidepanel/sidepanel.html?tabId={key[2:]}")
    panel.wait_for_selector("#verdict", timeout=15000)
    text = panel.text_content("#app")
    for needle in ("Piyasa özeti", "Gizli kusur röntgeni", "Teklif & pazarlık", "Ekspertiz kontrol listesi",
                   "ŞASE UCU işlemi", "Açılış teklifi", "ekspertize götürmeye değer"):
        assert needle in text, needle
    assert "Üst sınır (yalnız sana)" in text
    assert panel.locator("#copy").count() == 1
    panel.evaluate("""() => { window.__copied = null;
        navigator.clipboard.writeText = async (t) => { window.__copied = t; }; }""")
    panel.click("#copy")
    panel.wait_for_function("window.__copied !== null")
    copied = panel.evaluate("window.__copied")
    d = session_state(sw)[key]["data"]
    fmt = lambda n: f"{n:,}".replace(",", ".")
    assert "ekspertiz şartıyla" in copied and f"{fmt(d['tavsiye_teklif'])} TL" in copied
    assert "sag arka camurluk değişen" in copied                           # yapısal kusur, LLM değil
    if d["ust_sinir"] != d["tavsiye_teklif"]:
        assert fmt(d["ust_sinir"]) not in copied                            # üst sınır satıcıya gidecek metinde YOK
    panel.close()


def test_unreadable_page_makes_no_verdict_and_no_api_call(browser_ctx, backend):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    before = backend["db"]().query(Verdict).count()
    calls = ScriptedLLM.calls
    page = ctx.new_page()
    page.goto(BAD_URL)
    page.wait_for_function(
        "document.getElementById('aracx-badge-host') && document.getElementById('aracx-badge-host').shadowRoot"
        ".querySelector('button').textContent.includes('okunamadı')", timeout=30000)
    assert backend["db"]().query(Verdict).count() == before and ScriptedLLM.calls == calls
    states = [v["status"] for v in session_state(sw).values()]
    assert "unreadable" in states
    page.close()


# ------------------------------------------------------------------ arama sayfası
def test_search_page_adds_neutral_price_badges_and_remembers_rows(browser_ctx, backend):
    ctx = browser_ctx["ctx"]
    page = ctx.new_page()
    page.goto(SEARCH_URL)
    page.wait_for_selector(".aracx-badge", timeout=60000)
    page.wait_for_function("document.querySelectorAll('.aracx-badge').length >= 5", timeout=30000)
    rows = page.eval_on_selector_all(
        "tr.searchResultsItem",
        "els => els.map(e => [e.dataset.id, Array.from(e.querySelectorAll('.aracx-badge')).map(b => b.className + '|' + b.textContent)])")
    by = {i: b for i, b in rows}
    assert "aracx-avantajli" in by["1111111111"][0] and "avantajlı" in by["1111111111"][0]
    assert "aracx-piyasada" in by["2222222222"][0]
    assert "aracx-pahali" in by["3333333333"][0] and "Pahalı" in by["3333333333"][0]
    assert "aracx-cok_ucuz_suphe" in by["4444444444"][0] and "nedenini sor" in by["4444444444"][0]
    assert "aracx-emsal_yetersiz" in by["5555555555"][0]
    assert by["6666666666"] == []                                          # okunamayan satır rozetsiz
    assert all("kelepir" not in b.lower() for v in by.values() for b in v)
    assert "okunamadı" in page.inner_text(".aracx-status") and "karar değildir" in page.inner_text(".aracx-status")

    db = backend["db"]()
    assert db.get(Listing, "1111111111") is not None and db.get(Listing, "5555555555") is None   # tanınmayan kaydedilmedi
    page.close()


def test_extension_never_requests_sahibinden_by_itself(browser_ctx):
    """Sahibinden'e giden her istek test sayfalarının kendi gezintisidir; service worker/eklenti hiç istek atmaz."""
    hits = browser_ctx["hits"]
    assert hits, "test sayfaları yüklenmedi"
    assert all(not from_sw for _, from_sw in hits)
    allowed = {DETAIL_URL, SEARCH_URL, BAD_URL}
    stray = [u for u, _ in hits if u.split("?")[0] not in allowed and not u.endswith(("favicon.ico",))]
    assert stray == [], f"beklenmeyen sahibinden isteği: {stray}"


def test_wrong_token_is_reported_not_crashing(browser_ctx):
    ctx, sw = browser_ctx["ctx"], browser_ctx["sw"]
    sw.evaluate("() => chrome.storage.local.set({token: 'yanlis-yanlis-yanlis-yanlis'})")
    page = ctx.new_page()
    page.goto(DETAIL_URL)
    page.wait_for_function(
        "document.getElementById('aracx-badge-host').shadowRoot.querySelector('button').textContent.includes('Jeton')",
        timeout=30000)
    page.close()
    sw.evaluate("t => chrome.storage.local.set({token: t})", TOKEN)
