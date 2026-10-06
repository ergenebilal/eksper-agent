"""Engel (BLOCKED) koruması: backoff ve ardışık blok sayımı. Durum fetch_logs tablosundan türetilir.

Kurallar (CLAUDE.md 2-3): doğrulama sayfası çıkarsa çözülmeye/aşılmaya çalışılmaz; sistem durur,
bekler ve kullanıcıya haber verir. Ardışık bloklarda bekleme süresi artar (30dk → 2sa → 6sa).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from arac_eksper.config.settings import settings
from arac_eksper.storage.models import FetchLog, Watch


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def consecutive_blocks(db: Session) -> int:
    """En son kayıttan geriye doğru, araya başarılı çekim girmeden kaç BLOCKED var."""
    n = 0
    for log in db.query(FetchLog).order_by(FetchLog.id.desc()).limit(20):
        if log.status == "BLOCKED":
            n += 1
        elif log.status == "OK":
            break
    return n


def backoff_minutes(n_blocks: int) -> int:
    schedule = settings.block_backoff_minutes
    return schedule[min(max(n_blocks, 1), len(schedule)) - 1]


def blocked_until(db: Session) -> Optional[datetime]:
    last = db.query(FetchLog).order_by(FetchLog.id.desc()).first()
    if not last or last.status != "BLOCKED":
        return None
    return as_utc(last.timestamp) + timedelta(minutes=backoff_minutes(consecutive_blocks(db)))


def is_blocked_now(db: Session) -> Optional[datetime]:
    until = blocked_until(db)
    if until and datetime.now(timezone.utc) < until:
        return until
    return None


def pause_watches_if_needed(db: Session) -> bool:
    """Ardışık blok sayısı eşiğe ulaştıysa tüm radarları duraklatır. Yeniden başlatma: `arac watch resume`."""
    if consecutive_blocks(db) < settings.watch_pause_after_blocks:
        return False
    active = db.query(Watch).filter(Watch.is_active == True).all()  # noqa: E712
    for w in active:
        w.is_active = False
    db.commit()
    return bool(active)
