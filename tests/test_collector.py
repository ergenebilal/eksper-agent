import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from arac_eksper.storage.models import Base, FetchLog
from arac_eksper.collector.playwright_collector import PlaywrightCollector
from arac_eksper.config.settings import settings

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()

def test_check_rate_limit(db_session, monkeypatch):
    # Ayarları kopyala ve max_pages_per_hour'u 2 yapalım
    monkeypatch.setattr(settings, "max_pages_per_hour", 2)
    
    collector = PlaywrightCollector(db_session)
    
    # Boş db, true dönmeli
    assert collector._check_rate_limit() is True
    
    # 1. log (şimdi)
    db_session.add(FetchLog(url="url1", status="OK", timestamp=datetime.now(timezone.utc)))
    db_session.commit()
    assert collector._check_rate_limit() is True
    
    # 2. log (şimdi)
    db_session.add(FetchLog(url="url2", status="OK", timestamp=datetime.now(timezone.utc)))
    db_session.commit()
    
    # 2 limitine ulaştık, false dönmeli
    assert collector._check_rate_limit() is False
    
    # 3. log (2 saat önce)
    db_session.add(FetchLog(url="url3", status="OK", timestamp=datetime.now(timezone.utc) - timedelta(hours=2)))
    db_session.commit()
    
    # Eski logları limit saymamalı ama son 1 saatte 2 tane olduğu için yine False
    assert collector._check_rate_limit() is False
