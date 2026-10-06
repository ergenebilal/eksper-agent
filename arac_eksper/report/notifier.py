"""Tek bildirim kapısı. Olay her zaman events tablosuna yazılır; notify_mode=arac ise Telegram'a da gider.
notify_mode=jeff: Jeff `arac events --json` ile okur (çift bildirim olmaz). notify_mode=off: gönderilmez."""
from sqlalchemy.orm import Session
from arac_eksper.config.settings import settings
from arac_eksper.report import telegram
from arac_eksper.storage import repo


def emit(db: Session, type_: str, text: str, ilan_no: str | None = None,
         watch_id: int | None = None, payload: dict | None = None, feedback_buttons: bool = False):
    ev = repo.add_event(db, type_, text, ilan_no=ilan_no, watch_id=watch_id, payload=payload)
    if settings.notify_mode == "arac":
        if telegram.send_telegram_message(text, ilan_no if feedback_buttons else None):
            ev.delivered = True
            db.commit()
    return ev


def blocked_text(note: str | None) -> str:
    return ("⚠️ sahibinden doğrulama/engel sayfası çıkardı. Manuel müdahale gerekli, otomatik deneme durduruldu."
            + (f"\n{note}" if note else ""))
