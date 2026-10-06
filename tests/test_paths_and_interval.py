"""Y4: korumalar çalışma dizininden ve tetikleme yolundan bağımsız olmalı."""
import os
from pathlib import Path
from arac_eksper.config.settings import Settings, PROJECT_ROOT, DATA_DIR


def test_relative_paths_anchor_to_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings(database_url="sqlite:///data/arac.db", browser_profile_dir="browser_profile")
    assert s.database_url == "sqlite:///" + (PROJECT_ROOT / "data/arac.db").as_posix()
    assert Path(s.browser_profile_dir) == PROJECT_ROOT / "browser_profile"


def test_absolute_and_memory_urls_untouched():
    assert Settings(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"
    p = (Path(os.getcwd()).anchor + "x/y.db").replace("\\", "/")
    assert Settings(database_url=f"sqlite:///{p}").database_url == f"sqlite:///{p}"


def test_data_dir_is_absolute():
    assert DATA_DIR.is_absolute() and DATA_DIR == PROJECT_ROOT / "data"


def _session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from arac_eksper.storage.db import Base
    eng = create_engine(f"sqlite:///{tmp_path/'i.db'}")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_interval_elapsed_blocks_rapid_external_triggers(tmp_path):
    from datetime import datetime, timedelta, timezone
    from arac_eksper.storage.models import Watch, Event
    from arac_eksper.watcher import scheduler
    db = _session(tmp_path)
    w = Watch(name="w", criteria={}, interval_minutes=5)   # 5 < min 15 → 15 dk geçerli
    db.add(w); db.commit()
    assert scheduler.interval_elapsed(db, w)               # hiç tur yok
    db.add(Event(type="watch_run", text="x", watch_id=w.id, created_at=datetime.now(timezone.utc) - timedelta(minutes=14)))
    db.commit()
    assert not scheduler.interval_elapsed(db, w)
    db.add(Event(type="watch_run", text="x", watch_id=w.id, created_at=datetime.now(timezone.utc) - timedelta(minutes=16)))
    db.commit()
    assert scheduler.interval_elapsed(db, w)               # en yeni kayıt 16 dk önce: aralık doldu


def test_two_watches_run_serially_not_colliding(monkeypatch):
    """Y5: eşzamanlı tetiklenen iki radar kilide çarpıp atlanmaz, sırayla çalışır."""
    import threading, time
    from arac_eksper.watcher import scheduler
    active, peak = [0], [0]
    def fake(watch_id, force, enforce):
        active[0] += 1; peak[0] = max(peak[0], active[0]); time.sleep(0.05); active[0] -= 1; return watch_id
    monkeypatch.setattr(scheduler, "_run_watch_once", fake)
    res = []
    ts = [threading.Thread(target=lambda i=i: res.append(scheduler.run_watch_once(i))) for i in (1, 2, 3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(res) == [1, 2, 3] and peak[0] == 1
