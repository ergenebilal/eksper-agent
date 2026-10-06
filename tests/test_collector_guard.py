import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from arac_eksper.storage.models import Base, FetchLog, Watch
from arac_eksper.collector import guard
from arac_eksper.collector.playwright_collector import PlaywrightCollector, detect_block
from arac_eksper.collector.lock import collection_lock, CollectionBusy
from arac_eksper.config.settings import settings

OK_LIST = '<div class="list-item"><a class="ilan-link" href="/x">x</a></div> Bireysel Giriş Ray ID: 123'
CHALLENGE = "<html><body><div id='cf-browser-verification'>Just a moment...</div></body></html>"

@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)(); yield s; s.close()

def _log(db, status, minutes_ago=0):
    db.add(FetchLog(url="u", status=status, timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
    db.commit()

class FakeBrowserCollector(PlaywrightCollector):
    """Tarayıcıyı atlar; yanıtı kontrol edilebilir sahte sunucudan alır."""
    def __init__(self, db, responses):
        self.db = db; self.profile_dir = "x"; self.responses = list(responses); self.calls = 0
    async def _navigate(self, url, is_detail):
        self.calls += 1
        return self.responses.pop(0)
    async def _sleep_between_requests(self):
        pass

def test_detect_block_rules():
    assert detect_block(403, "", "x") and detect_block(429, "", "x")
    assert detect_block(200, CHALLENGE, "div.list-item")
    # eski genel marker'lar artık tek başına engel sayılmaz; ana element varsa sayfa sağlamdır
    assert not detect_block(200, OK_LIST, "div.list-item")
    assert not detect_block(200, "<html>Bireysel Giriş Ray ID</html>", "div.list-item")

def test_403_logs_blocked_and_blocks_next_request(db, monkeypatch):
    c = FakeBrowserCollector(db, [(403, ""), (200, OK_LIST)])
    r1 = asyncio.run(c.fetch_list("u1"))
    assert r1.status == "BLOCKED" and c.calls == 1
    r2 = asyncio.run(c.fetch_list("u2"))      # backoff: tarayıcıya hiç gidilmemeli
    assert r2.status == "BLOCKED" and c.calls == 1
    assert db.query(FetchLog).count() == 1    # bekleme sırasındaki reddetme loglanmaz

def test_backoff_schedule_and_expiry(db):
    _log(db, "BLOCKED", minutes_ago=31)
    assert guard.consecutive_blocks(db) == 1 and guard.is_blocked_now(db) is None   # 30 dk doldu
    _log(db, "BLOCKED", minutes_ago=31)
    assert guard.consecutive_blocks(db) == 2 and guard.backoff_minutes(2) == 120
    assert guard.is_blocked_now(db) is not None                                      # 2 sa dolmadı

def test_success_resets_chain(db):
    _log(db, "BLOCKED", 500); _log(db, "BLOCKED", 400); _log(db, "OK", 300)
    assert guard.consecutive_blocks(db) == 0 and guard.blocked_until(db) is None

def test_three_blocks_pause_watches(db):
    db.add(Watch(name="w", criteria={})); db.commit()
    for m in (900, 800): _log(db, "BLOCKED", m)
    assert guard.pause_watches_if_needed(db) is False
    _log(db, "BLOCKED", 700)
    assert guard.pause_watches_if_needed(db) is True
    assert db.query(Watch).first().is_active is False

def test_rate_limit_stops_requests(db, monkeypatch):
    monkeypatch.setattr(settings, "max_pages_per_hour", 1)
    c = FakeBrowserCollector(db, [(200, OK_LIST), (200, OK_LIST)])
    assert asyncio.run(c.fetch_list("u1")).status == "OK"
    r = asyncio.run(c.fetch_list("u2"))
    assert r.status == "RATE_LIMITED" and c.calls == 1

def test_challenge_page_is_blocked(db):
    c = FakeBrowserCollector(db, [(200, CHALLENGE)])
    assert asyncio.run(c.fetch_list("u")).status == "BLOCKED"

def test_collection_lock_is_exclusive(tmp_path):
    p = tmp_path / "l.lock"
    with collection_lock(p):
        with pytest.raises(CollectionBusy):
            with collection_lock(p):
                pass
    with collection_lock(p):   # bırakıldıktan sonra yeniden alınabilir
        pass
