import requests
from arac_eksper.config.settings import settings


def telegram_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_telegram_message(text: str, ilan_no: str | None = None) -> bool:
    """Düz metin gönderir (parse_mode yok: ilan başlıklarındaki _ * karakterleri Markdown'ı bozmasın).
    ilan_no verilirse 👍/👎 geri bildirim butonları eklenir. Başarıyı döner; anahtar loglanmaz."""
    if not telegram_configured():
        print("Telegram bot_token veya chat_id ayarlanmamış (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
        return False

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if ilan_no:
        payload["reply_markup"] = {"inline_keyboard": [[
            {"text": "👍 İyi", "callback_data": f"fb_pos_{ilan_no}"},
            {"text": "👎 Kötü", "callback_data": f"fb_neg_{ilan_no}"},
        ]]}
    try:
        r = requests.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                          json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001  (URL token içerir; yalnızca hata türünü yaz)
        print(f"Telegram gönderim hatası: {type(e).__name__}")
        return False
