"""Telegram 👍/👎 geri bildirimi: callback_data -> feedbacks tablosu. `arac telegram poll` ile dinlenir."""
import time
from pathlib import Path
import requests
from sqlalchemy.orm import Session
from arac_eksper.config.settings import settings
from arac_eksper.storage import repo

OFFSET_FILE = Path("data/telegram_offset")


def process_callback(db: Session, data: str) -> bool:
    if data.startswith("fb_pos_"):
        repo.add_feedback(db, data[len("fb_pos_"):], True)
        return True
    if data.startswith("fb_neg_"):
        repo.add_feedback(db, data[len("fb_neg_"):], False)
        return True
    return False


def poll_once(db: Session, timeout: int = 25) -> int:
    """getUpdates ile bekleyen butonları işler; işlenen sayıyı döner."""
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    offset = int(OFFSET_FILE.read_text()) if OFFSET_FILE.exists() else 0
    r = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": timeout,
                     "allowed_updates": '["callback_query"]'}, timeout=timeout + 10)
    r.raise_for_status()
    handled = 0
    for upd in r.json().get("result", []):
        offset = upd["update_id"] + 1
        cq = upd.get("callback_query")
        if cq and str(cq.get("message", {}).get("chat", {}).get("id")) == str(settings.telegram_chat_id):
            if process_callback(db, cq.get("data", "")):
                handled += 1
                requests.post(f"{base}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": "Kaydedildi"}, timeout=10)
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))
    return handled


def poll_forever(db: Session):
    while True:
        try:
            poll_once(db)
        except Exception as e:  # noqa: BLE001
            print(f"poll hatası: {type(e).__name__}")
            time.sleep(10)
