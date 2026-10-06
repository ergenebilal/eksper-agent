from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    max_pages_per_hour: int = 40
    browser_profile_dir: str = "browser_profile"
    database_url: str = "sqlite:///data/arac.db"
    openai_api_key: str = ""
    
    llm_base_url: str = "http://127.0.0.1:8999/v1"
    llm_api_key: str = "sk-placeholder"
    llm_model_fast: str = "fast-model"
    llm_model_strong: str = "strong-model"

    # Bildirim: "arac" = arac Telegram'a kendisi gönderir, "jeff" = yalnızca events tablosuna yazar
    # (Jeff `arac events --json` ile okur), "off" = hiçbir yere gönderilmez.
    notify_mode: str = "arac"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Zamanlama: "internal" = arac kendi APScheduler'ını çalıştırır, "external" = dışarıdan
    # (cron/Jeff/n8n) `arac watch run --once` ile tetiklenir.
    scheduler_mode: str = "internal"
    min_watch_interval_minutes: int = 15

    # Toplama güvenliği (CLAUDE.md kural 1-2)
    block_backoff_minutes: list[int] = [30, 120, 360]
    watch_pause_after_blocks: int = 3
    max_details_per_search: int = 8
    max_details_per_watch_run: int = 5
    search_pages: int = 2
    lock_stale_minutes: int = 45
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
