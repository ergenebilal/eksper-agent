import sys
"""Radar zamanlayıcı. SCHEDULER_MODE=internal: bu süreç APScheduler çalıştırır.
external: `arac watch run --once` dışarıdan (cron/Jeff/n8n) tetiklenir; bu modül başlatılmaz."""
import asyncio
import threading
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from arac_eksper.config.settings import settings
from arac_eksper.storage.db import SessionLocal
from arac_eksper.storage.models import Watch
from arac_eksper.watcher import runner


# Aynı süreçteki radar işleri sırayla çalışır: aksi halde eşzamanlı başlayan ikinci radar
# toplama kilidine çarpıp her aralıkta atlanırdı (açlık).
_RUN_LOCK = threading.Lock()


def interval_elapsed(db, w) -> bool:
    """Son tur, radarın aralığından (en az min_watch_interval_minutes) yakın bir zamanda başladıysa False.
    `--once`/dış tetikleyici (cron/Jeff) bu yüzden aralığı atlatamaz."""
    from datetime import timedelta, timezone
    from arac_eksper.collector.guard import as_utc
    from arac_eksper.storage.models import Event
    last = (db.query(Event).filter(Event.type == "watch_run", Event.watch_id == w.id)
            .order_by(Event.id.desc()).first())
    if not last or not last.created_at:
        return True
    minutes = max(w.interval_minutes or 30, settings.min_watch_interval_minutes)
    return datetime.now(timezone.utc) - as_utc(last.created_at) >= timedelta(minutes=minutes)


def run_watch_once(watch_id: int, force: bool = False, enforce_interval: bool = False):
    """enforce_interval=True: dış tetikleyiciler (`--once`) için; iç zamanlayıcı kendi ritmini zaten tutar."""
    with _RUN_LOCK:
        return _run_watch_once(watch_id, force, enforce_interval)


def _run_watch_once(watch_id: int, force: bool = False, enforce_interval: bool = False):
    """Tek bir watch'ı bir tur çalıştırır. (RunResult | None) döner; saat dışındaysa None."""
    from arac_eksper.collector.playwright_collector import PlaywrightCollector
    from arac_eksper.llm.client import OpenAIClient
    db = SessionLocal()
    try:
        w = db.get(Watch, watch_id)
        if not w or not w.is_active:
            return None
        if not force and not runner.in_active_hours(datetime.now(), w.active_hours):
            return None
        if enforce_interval and not interval_elapsed(db, w):
            return None
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Radar çalışıyor: {w.name}", file=sys.stderr)
        return asyncio.run(runner.run_watch(db, w, PlaywrightCollector(db), OpenAIClient()))
    finally:
        db.close()


def send_daily_summary():
    from arac_eksper.report import notifier
    db = SessionLocal()
    try:
        notifier.emit(db, "daily_summary", runner.build_daily_summary(db))
    finally:
        db.close()


def run_scheduler():
    scheduler = BlockingScheduler()
    db = SessionLocal()
    try:
        watches = db.query(Watch).filter(Watch.is_active == True).all()  # noqa: E712
        for w in watches:
            minutes = max(w.interval_minutes or 30, settings.min_watch_interval_minutes)
            scheduler.add_job(run_watch_once, "interval", minutes=minutes, args=[w.id],
                              id=f"watch-{w.id}", max_instances=1, coalesce=True)
    finally:
        db.close()
    scheduler.add_job(send_daily_summary, "cron", hour=21, minute=30, id="daily-summary")
    print(f"Radar zamanlayıcısı başlatıldı ({len(watches)} radar). Durdurmak için Ctrl+C.", file=sys.stderr)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
