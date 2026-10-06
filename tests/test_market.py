import pytest
from datetime import datetime, timezone, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from arac_eksper.storage.models import Base, Listing
from arac_eksper.analysis.market import get_market_stats
from arac_eksper.schemas import ListingDetail

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()

def test_market_bmw_pollution_scenario(db_session):
    # Test: BMW kirlilik senaryosu (5 Megane@900k + 10 BMW@3M → medyan 900k)
    # Hedef araç: Renault Megane
    target = ListingDetail(
        ilan_no="TARGET_1", url="url", baslik="Megane 1.5 dCi",
        marka="Renault", model="Megane", seri="1.5 dCi Touch",
        fiyat=950000, yil=2018, km=100000, il="Bursa", ilan_tarihi=date.today(),
        vites="Otomatik", yakit="Dizel", source="detail",
        aciklama="Temiz araba", fetched_at=datetime.now(timezone.utc)
    )
    
    # Hedef aracı da DB'ye ekleyelim (örneklemden dışlanmalı)
    db_session.add(Listing(
        ilan_no="TARGET_1", url="url", baslik="Megane 1.5 dCi",
        marka="Renault", model="Megane", seri="1.5 dCi Touch",
        fiyat=950000, yil=2018, km=100000, il="Bursa", ilan_tarihi=date.today(),
        vites="Otomatik", yakit="Dizel", source="detail", fetched_at=datetime.now(timezone.utc)
    ))
    
    # 5 adet Renault Megane emsali (fiyat 900k, 910k, 890k, 900k, 920k) -> Medyan 900k
    prices = [900000, 910000, 890000, 900000, 920000]
    for i, p in enumerate(prices):
        db_session.add(Listing(
            ilan_no=f"MEGANE_{i}", url="url", baslik="Megane",
            marka="Renault", model="Megane", seri="1.5 dCi Touch",
            fiyat=p, yil=2018, km=100000, il="Bursa", ilan_tarihi=date.today(),
            vites="Otomatik", yakit="Dizel", source="list", fetched_at=datetime.now(timezone.utc)
        ))
        
    # 10 adet BMW emsali (Kirlilik, marka filtresi olmazsa araya karışır)
    for i in range(10):
        db_session.add(Listing(
            ilan_no=f"BMW_{i}", url="url", baslik="BMW 320i",
            marka="BMW", model="3 Serisi", seri="320i",
            fiyat=3000000, yil=2018, km=100000, il="İstanbul", ilan_tarihi=date.today(),
            vites="Otomatik", yakit="Dizel", source="list", fetched_at=datetime.now(timezone.utc)
        ))
        
    db_session.commit()
    
    stats = get_market_stats(db_session, target)
    
    # Hedef araç çıkarıldığında 5 araç kalıyor, geniş aramaya gideceği için güven=dusuk, n=5 olmalı.
    assert stats.n == 5
    assert stats.medyan == 900000 # BMW'ler elendiği için 900k olmalı. (BMWler kalsaydı 3 milyonlara çıkardı)
    assert stats.guven == "dusuk" # n=5 olduğu için (8'den küçük)
