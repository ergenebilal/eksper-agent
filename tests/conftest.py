import pytest
from arac_eksper.collector import lock
from arac_eksper.config.settings import settings


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Testler gerçek kilit dosyasına, Telegram'a ya da veri dizinine dokunmasın."""
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "collect.lock")
    monkeypatch.setattr(settings, "notify_mode", "off")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")


@pytest.fixture(autouse=True)
def _category_map(monkeypatch):
    from arac_eksper.collector import url_builder
    monkeypatch.setattr(url_builder, "load_category_map",
                        lambda: {"Renault": {"Megane": {"_model": "renault-megane", "1.5 dCi Touch": "renault-megane-1.5-dci-touch"}}})
