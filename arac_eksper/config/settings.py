from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Göreli yollar çalıştırma dizinine değil proje köküne bağlanır: aksi halde başka dizinden (cron/Jeff)
# çalıştırınca ayrı DB, ayrı kilit ve ayrı saatlik limit oluşurdu.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

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

    # Panel: token boşsa/zayıfsa panel BAŞLAMAZ (varsayılan yok). Varsayılan bind yalnızca yerel makine.
    panel_token: str = ""
    panel_host: str = "127.0.0.1"
    panel_port: int = 8990
    panel_session_hours: int = 12
    panel_allowed_hosts: list[str] = ["127.0.0.1", "localhost", "::1"]   # Host başlığı beyaz listesi (DNS rebinding)
    xray_host: str = "127.0.0.1"      # CyberOto API (arac xray serve)
    xray_port: int = 8991
    xray_forwarded_allow_ips: str = "127.0.0.1"   # X-Forwarded-For'a güvenilecek ters vekil (Caddy) adresleri
    panel_cookie_secure: bool = False   # https (Tailscale Serve vb.) arkasında True yap

    # Chrome eklentisi API'si (/api/v1): ayrı token; boşsa/16 karakterden kısaysa API KAPALI
    extension_token: str = ""
    xray_second_pass: str = "hard"     # all | hard | off: güçlü modelle ikinci geçiş (her geçiş ~15-25 sn). hard = yalnız 🔴 nedeni olabilecek iddialarda
    analyze_daily_limit: int = 300      # 24 saatte en fazla bu kadar YENİ LLM çözümlemesi (önbellek isabeti sayılmaz)
    # Davetli kullanıcılar (arac xray user add): kişi başı anahtar + günlük kota. EXTENSION_TOKEN = sahip, kotasız.
    xray_accounts_db: str = "data/xray_accounts.db"
    user_daily_quota: int = 30          # davetli kullanıcı başına günlük analiz (LLM) sınırı
    user_daily_batch: int = 400         # davetli başına günlük arama sayfası rozeti isteği (toplu kopyalamaya karşı)
    feedback_daily_limit: int = 50
    # E-posta koduyla giriş ve davet (SMTP). Boşsa kod gönderilemez (açıkça hata verir).
    smtp_host: str = ""
    smtp_port: int = 587               # 587 = STARTTLS, 465 = SSL
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                # ör. otoxray@cybergene.co
    store_url: str = ""                # davet e-postasındaki Chrome Web Store bağlantısı
    public_url: str = "https://cyberoto.cybergene.co"  # e-postalardaki logo vb. için genel adres (2026-10-07: alan adı taşındı)
    # Yönetim sayfası (/yonetim): yalnız bu adreslere giriş kodu gönderilir
    admin_emails: list[str] = []
    admin_api_token: str = ""          # Jeff yönetici API'si (/admin-api/v1): en az 32 karakter; boşsa API kapalı. Yalnız 127.0.0.1
    admin_cookie_secure: bool = True   # https arkasında True (yerel http denemede False)

    # Toplama güvenliği (CLAUDE.md kural 1-2)
    block_backoff_minutes: list[int] = [30, 120, 360]
    watch_pause_after_blocks: int = 3
    max_details_per_search: int = 8
    max_details_per_watch_run: int = 5
    search_pages: int = 2
    lock_stale_minutes: int = 45
    
    @field_validator("database_url")
    @classmethod
    def _abs_sqlite(cls, v: str) -> str:
        prefix = "sqlite:///"
        if v.startswith(prefix) and v != "sqlite:///:memory:":
            path = Path(v[len(prefix):])
            if not path.is_absolute():
                return prefix + (PROJECT_ROOT / path).as_posix()
        return v

    @field_validator("browser_profile_dir")
    @classmethod
    def _abs_profile(cls, v: str) -> str:
        path = Path(v)
        return v if path.is_absolute() else str(PROJECT_ROOT / path)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
