"""Y6: --json modunda stdout yalnızca JSON'dur; kütüphane katmanı stdout'a yazmaz."""
import json
from typer.testing import CliRunner
from arac_eksper.cli import app


def test_no_library_prints_to_stdout(capsys, monkeypatch):
    from arac_eksper.config.settings import settings
    from arac_eksper.report import telegram
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert telegram.send_telegram_message("x") is False
    out = capsys.readouterr()
    assert out.out == "" and "Telegram" in out.err


def test_watch_run_once_json_is_pure_json(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from arac_eksper import cli
    from arac_eksper.storage.db import Base
    from arac_eksper.storage.models import Watch
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    s.add(Watch(name="w", criteria={"marka": "Renault", "model": "Megane", "max_butce": 1}, active_hours="00:00-23:59"))
    s.commit(); s.close()
    monkeypatch.setattr(cli, "_session", Session)
    from arac_eksper.watcher import scheduler
    monkeypatch.setattr(scheduler, "SessionLocal", Session)
    import asyncio
    from arac_eksper.watcher import runner
    from arac_eksper import pipeline
    async def fake_run(db, w, c, l):
        r = pipeline.RunResult(); return r
    monkeypatch.setattr(runner, "run_watch", fake_run)
    monkeypatch.setattr("arac_eksper.collector.playwright_collector.PlaywrightCollector", lambda db: None)
    monkeypatch.setattr("arac_eksper.llm.client.OpenAIClient", lambda: None)
    r = CliRunner().invoke(app, ["watch", "run", "--once", "--json"])
    json.loads(r.stdout)           # "Radar çalışıyor" satırı stdout'ta olsaydı burada patlardı
    assert "Radar çalışıyor" in r.stderr
