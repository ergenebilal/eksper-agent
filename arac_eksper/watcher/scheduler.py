"""Radar zamanlayıcı. SCHEDULER_MODE=internal: bu süreç APScheduler çalıştırır.
external: `arac watch run --once` dışarıdan (cron/Jeff/n8n) tetiklenir; bu modül başlatılmaz."""
import asyncio
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from arac_eksper.config.settings import settings
from arac_eksper.storage.db import SessionLocal
from arac_eksper.storage.models import Watch
from arac_eksper.watcher import runner


def run_watch_once(watch_id: int, force: bool = False):
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
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Radar çalışıyor: {w.name}")
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
    print(f"Radar zamanlayıcısı başlatıldı ({len(watches)} radar). Durdurmak için Ctrl+C.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
