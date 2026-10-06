import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from arac_eksper import pipeline
from arac_eksper.config.settings import settings
from arac_eksper.report import telegram
from arac_eksper.report.feedback import process_callback
from arac_eksper.storage import repo
from arac_eksper.storage.models import Base, Event, FetchLog, Feedback, Notification, Watch
from arac_eksper.watcher import diff, runner
from tests.helpers import FakeCollector, FakeLLM, DownLLM, list_html, detail_html, ok, blocked

MARKET = [(f"20{i:02d}", 900_000 + i * 2_000, "Megane") for i in range(7)]
PRICES = {no: fiyat for no, fiyat, _ in MARKET}


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def watch(db):
    w = Watch(name="megane", criteria={"marka": "Renault", "model": "Megane", "max_butce": 1_000_000, "min_yil": 2020})
    db.add(w); db.commit()
    return w


def run(coro):
    return asyncio.run(coro)


def events(db, type_):
    return db.query(Event).filter_by(type=type_).all()


def test_notifies_green_once_and_never_twice(db, watch):
    col = FakeCollector([ok(list_html([("1001", 820_000, "Temiz Megane")] + MARKET))],
                        {"1001": ok(detail_html("1001", 820_000))}, auto_prices=PRICES)
    r1 = run(runner.run_watch(db, watch, col, FakeLLM()))
    ours = lambda: [e for e in events(db, "alinir") if e.ilan_no == "1001"]
    assert len(ours()) == 1 and "yeni ilan" in ours()[0].text
    for _ in range(3):   # aynı liste tekrar tekrar: 1001 için ikinci bildirim ASLA gitmemeli
        run(runner.run_watch(db, watch, col, FakeLLM()))
    assert len(ours()) == 1 and col.detail_calls.count("1001") == 1
    assert db.query(Notification).filter_by(ilan_no="1001").count() == 1


def test_backlog_is_evaluated_across_runs_not_dropped(db, watch, monkeypatch):
    """İlk taramada tur limiti (5) yüzünden kalan ilanlar 'görüldü' diye unutulmamalı."""
    monkeypatch.setattr(settings, "max_details_per_watch_run", 3)
    col = FakeCollector([ok(list_html(MARKET))], auto_prices=PRICES)
    run(runner.run_watch(db, watch, col, FakeLLM()))
    assert len(col.detail_calls) == 3
    run(runner.run_watch(db, watch, col, FakeLLM()))
    run(runner.run_watch(db, watch, col, FakeLLM()))
    assert sorted(set(col.detail_calls)) == sorted(PRICES), "7 ilanın hepsi sonunda değerlendirilmiş olmalı"
    assert len(col.detail_calls) == 7, "hiçbir ilan iki kez çekilmemeli"


def test_non_green_is_never_notified(db, watch):
    # fiyat piyasanın üstünde -> DÜŞÜNÜLEBİLİR; bildirim YOK
    col = FakeCollector([ok(list_html([("1001", 1_000_000, "Pahalı")] + MARKET))],
                        {"1001": ok(detail_html("1001", 1_000_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col, FakeLLM()))
    assert [e for e in events(db, "alinir") if e.ilan_no == "1001"] == []
    assert repo.latest_verdict_row(db, "1001").etiket == "DUSUNULEBILIR"


def test_price_drop_promotes_to_green_and_notifies(db, watch):
    col1 = FakeCollector([ok(list_html([("1001", 1_000_000, "Megane")] + MARKET))],
                         {"1001": ok(detail_html("1001", 1_000_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col1, FakeLLM()))
    assert [e for e in events(db, "alinir") if e.ilan_no == "1001"] == []
    col2 = FakeCollector([ok(list_html([("1001", 850_000, "Megane")] + MARKET))],
                         {"1001": ok(detail_html("1001", 850_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col2, FakeLLM()))
    ev = [e for e in events(db, "alinir") if e.ilan_no == "1001"]
    assert len(ev) == 1 and "fiyat düştü" in ev[0].text and col2.detail_calls[0] == "1001"


def test_republished_listing_is_detected(db, watch):
    col1 = FakeCollector([ok(list_html([("1001", 1_000_000, "Aynı Araç")] + MARKET))],
                         {"1001": ok(detail_html("1001", 1_000_000, baslik="Aynı Araç"))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col1, FakeLLM()))
    summaries = [s for s in __import__("arac_eksper.parser.list_parser", fromlist=["parse"]).parse(
        list_html([("9999", 850_000, "Aynı  Araç")] + MARKET))[0]]
    cs = diff.detect_changes(db, summaries, "Renault", "Megane")
    assert [(s.ilan_no, old) for s, old in cs.republished] == [("9999", "1001")]
    assert all(s.ilan_no != "9999" for s in cs.new)


def test_block_emits_event_and_third_consecutive_block_pauses_watchers(db, watch):
    for i in range(3):   # ardışık 3 engel (hepsinin bekleme süresi dolmuş)
        db.add(FetchLog(url="u", status="BLOCKED", timestamp=datetime.now(timezone.utc) - timedelta(hours=12 - i)))
    db.commit()
    r = run(runner.run_watch(db, watch, FakeCollector([blocked()]), FakeLLM()))
    assert r.status == "BLOCKED" and len(events(db, "blocked")) == 1
    db.refresh(watch)
    assert watch.is_active is False and len(events(db, "watch_paused")) == 1


def test_backoff_wait_makes_no_request_and_no_new_blocked_event(db, watch):
    db.add(FetchLog(url="u", status="BLOCKED")); db.commit()
    col = FakeCollector([ok(list_html(MARKET))])
    r = run(runner.run_watch(db, watch, col, FakeLLM()))
    assert r.status == "BLOCKED" and col.list_calls == 0 and events(db, "blocked") == []


def test_pending_analysis_is_retried_without_page_cost(db, watch):
    col = FakeCollector([ok(list_html([("1001", 820_000, "Temiz Megane")] + MARKET))],
                        {"1001": ok(detail_html("1001", 820_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col, DownLLM()))            # LLM kapalı: beklemede
    assert repo.latest_verdict_row(db, "1001").beklemede and events(db, "alinir") == []
    run(runner.run_watch(db, watch, col, FakeLLM()))            # havuz geri geldi
    assert col.detail_calls.count("1001") == 1, "bekleyen analiz yeniden sayfa çekmemeli"
    assert repo.latest_verdict_row(db, "1001").beklemede is False
    assert len([e for e in events(db, "alinir") if e.ilan_no == "1001"]) == 1


def test_run_status_event_proves_radar_ran(db, watch):
    col = FakeCollector([ok(list_html(MARKET))])
    run(runner.run_watch(db, watch, col, FakeLLM()))
    ev = events(db, "watch_run")
    assert len(ev) == 1 and ev[0].payload["status"] == "OK" and ev[0].watch_id == watch.id


# ---- bildirim kanalı ----
def test_jeff_mode_never_calls_telegram_but_stores_event(db, watch, monkeypatch):
    monkeypatch.setattr(settings, "notify_mode", "jeff")
    monkeypatch.setattr(telegram, "send_telegram_message", lambda *a, **k: pytest.fail("Telegram çağrılmamalı"))
    col = FakeCollector([ok(list_html([("1001", 820_000, "Temiz Megane")] + MARKET))],
                        {"1001": ok(detail_html("1001", 820_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col, FakeLLM()))
    ev = [e for e in events(db, "alinir") if e.ilan_no == "1001"]
    assert len(ev) == 1 and ev[0].delivered is False


def test_arac_mode_sends_with_feedback_buttons_and_marks_delivered(db, watch, monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "notify_mode", "arac")
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text, ilan_no=None: sent.append((text, ilan_no)) or True)
    col = FakeCollector([ok(list_html([("1001", 820_000, "Temiz Megane")] + MARKET))],
                        {"1001": ok(detail_html("1001", 820_000))}, auto_prices=PRICES)
    run(runner.run_watch(db, watch, col, FakeLLM()))
    mine = [x for x in sent if x[1] == "1001"]
    assert len(mine) == 1 and "ALINIR" in mine[0][0]
    assert [e for e in events(db, "alinir") if e.ilan_no == "1001"][0].delivered is True


def test_blocked_text_sent_in_arac_mode_without_buttons(db, watch, monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "notify_mode", "arac")
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text, ilan_no=None: sent.append((text, ilan_no)) or True)
    run(runner.run_watch(db, watch, FakeCollector([blocked()]), FakeLLM()))
    assert len(sent) == 1 and sent[0][1] is None and "Manuel müdahale" in sent[0][0]


def test_telegram_not_configured_does_not_crash():
    assert telegram.send_telegram_message("x") is False


def test_feedback_callbacks(db):
    assert process_callback(db, "fb_pos_1001") and process_callback(db, "fb_neg_1002")
    assert not process_callback(db, "baska")
    rows = db.query(Feedback).order_by(Feedback.id).all()
    assert [(r.ilan_no, r.is_positive) for r in rows] == [("1001", True), ("1002", False)]


# ---- aktif saatler ----
@pytest.mark.parametrize("hhmm,spec,expected", [
    ("09:00", "08:00-23:00", True), ("07:59", "08:00-23:00", False), ("23:30", "08:00-23:00", False),
    ("23:30", "22:00-06:00", True), ("03:00", "22:00-06:00", True), ("12:00", "22:00-06:00", False),
])
def test_active_hours(hhmm, spec, expected):
    h, m = map(int, hhmm.split(":"))
    assert runner.in_active_hours(datetime(2026, 10, 6, h, m), spec) is expected
