import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import date, datetime
from arac_eksper.storage.models import Base
from arac_eksper.storage import repo
from arac_eksper.schemas import ListingDetail

# In-memory veritabanı testi için
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)

def test_create_and_get_listing(db):
    detail = ListingDetail(
        ilan_no="123456789",
        url="http://test",
        baslik="Test Araç",
        fiyat=850000,
        yil=2018,
        km=95000,
        il="İstanbul",
        ilce="Kadıköy",
        ilan_tarihi=date.today(),
        aciklama="Temiz araç",
        fetched_at=datetime.utcnow()
    )
    
    # Create
    listing = repo.create_or_update_listing(db, detail)
    assert listing.ilan_no == "123456789"
    assert listing.fiyat == 850000
    
    # Read
    db_listing = repo.get_listing(db, "123456789")
    assert db_listing is not None
    assert db_listing.ilan_no == "123456789"
    assert db_listing.fiyat == 850000
    
    # Update
    detail.fiyat = 840000
    updated_listing = repo.create_or_update_listing(db, detail)
    assert updated_listing.fiyat == 840000
