import requests
from arac_eksper.config.settings import settings

def send_telegram_message(text: str, ilan_no: str):
    bot_token = getattr(settings, 'telegram_bot_token', None)
    chat_id = getattr(settings, 'telegram_chat_id', None)
    
    if not bot_token or not chat_id:
        print("Telegram bot_token veya chat_id ayarlanmamış.")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    reply_markup = {
        "inline_keyboard": [[
            {"text": "👍 İyi", "callback_data": f"fb_pos_{ilan_no}"},
            {"text": "👎 Kötü", "callback_data": f"fb_neg_{ilan_no}"}
        ]]
    }
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")
