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


def _row(i, fiyat, **kw):
    base = dict(ilan_no=f"E{i}", url="u", baslik=f"Megane {i}", marka="Renault", model="Megane", fiyat=fiyat, yil=2018,
                km=100000, il="Bursa", ilan_tarihi=date.today(), source="list", fetched_at=datetime.now(timezone.utc))
    base.update(kw)
    return Listing(**base)


def _target(**kw):
    base = dict(ilan_no="T", url="u", baslik="Hedef Megane", marka="Renault", model="Megane", fiyat=900000, yil=2018,
                km=100000, il="Bursa", ilan_tarihi=date.today(), vites="Otomatik", yakit="Dizel",
                aciklama="", fetched_at=datetime.now(timezone.utc))
    base.update(kw)
    return ListingDetail(**base)


def test_known_gearbox_rows_preferred_over_null_rows(db_session):
    for i in range(8):   # otomatik emsaller ~900k
        db_session.add(_row(i, 900000 + i * 1000, vites="Otomatik", yakit="Dizel"))
    for i in range(8, 20):   # vites bilinmeyen (liste kaydı) manuel olabilecek ucuz kayıtlar
        db_session.add(_row(i, 600000))
    db_session.commit()
    s = get_market_stats(db_session, _target())
    assert s.n == 8 and s.guven == "yuksek" and 900000 <= s.medyan <= 908000


def test_falls_back_to_null_rows_with_low_confidence(db_session):
    for i in range(6):
        db_session.add(_row(i, 900000))        # vites/yakıt NULL
    db_session.commit()
    s = get_market_stats(db_session, _target())
    assert s.n == 6 and s.guven == "dusuk"


def test_republished_twin_is_not_its_own_comparable(db_session):
    db_session.add(_row(1, 500000, baslik="Hedef Megane"))   # aynı başlık+yıl+km, farklı ilan no
    for i in range(2, 8):
        db_session.add(_row(i, 900000))
    db_session.commit()
    s = get_market_stats(db_session, _target())
    assert s.n == 6 and s.medyan == 900000


def test_listing_seen_again_stays_fresh(db_session):
    from datetime import timedelta
    from arac_eksper.storage import repo
    from arac_eksper.schemas import ListingSummary
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db_session.add(_row(1, 900000, fetched_at=old.replace(tzinfo=None)))
    db_session.commit()
    repo.create_or_update_listing_summary(
        db_session, ListingSummary(ilan_no="E1", url="u", baslik="Megane 1", fiyat=900000, yil=2018, km=100000,
                                   il="Bursa", ilan_tarihi=date.today()), "Renault", "Megane")
    row = db_session.get(Listing, "E1")
    assert datetime.utcnow() - row.fetched_at < timedelta(minutes=1)
