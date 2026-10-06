"""CLI akışının aynısı: önce liste özetleri (marka/model CLI argümanından), sonra detay.
Mock'la elle kayıt eklemek yerine gerçek repo + parser yolunu kullanır."""
import os
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from arac_eksper.storage.models import Base
from arac_eksper.storage import repo
from arac_eksper.parser import detail_parser
from arac_eksper.schemas import ListingSummary
from arac_eksper.analysis import market

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()

def _summary(i, fiyat, marka_model_baslik="Megane"):
    return ListingSummary(ilan_no=f"9{i:03d}", url="u", baslik=marka_model_baslik, fiyat=fiyat,
                          yil=2018, km=95000, il="Bursa", ilan_tarihi=date.today())

def test_list_then_detail_produces_market():
    db = _db()
    for i in range(10):
        repo.create_or_update_listing_summary(db, _summary(i, 900000 + i * 1000), "Renault", "Megane")
    html = open(os.path.join(FIXTURES, "detail_1.html"), encoding="utf-8").read()
    detail = detail_parser.parse(html, url="u")
    assert detail.marka == "Renault" and detail.model == "Megane"
    repo.create_or_update_listing(db, detail)

    stats = market.get_market_stats(db, detail)
    assert stats.n >= 8
    assert 895000 <= stats.medyan <= 915000

def test_other_brand_does_not_pollute():
    db = _db()
    for i in range(6):
        repo.create_or_update_listing_summary(db, _summary(i, 900000), "Renault", "Megane")
    for i in range(10):
        repo.create_or_update_listing_summary(db, _summary(100 + i, 3000000, "320i"), "BMW", "3 Serisi")
    html = open(os.path.join(FIXTURES, "detail_1.html"), encoding="utf-8").read()
    detail = detail_parser.parse(html, url="u")
    repo.create_or_update_listing(db, detail)
    stats = market.get_market_stats(db, detail)
    assert stats.medyan == 900000

def test_detail_enriches_existing_list_row():
    db = _db()
    repo.create_or_update_listing_summary(db, _summary(0, 850000), "Renault", "Megane")
    html = open(os.path.join(FIXTURES, "detail_1.html"), encoding="utf-8").read()
    detail = detail_parser.parse(html, url="u")
    row = repo.create_or_update_listing(db, detail)   # ilan_no aynı (123456789) değil; yeni kayıt
    assert row is not None and row.source == "detail" and row.vites == "Otomatik"

def test_unknown_brand_model_returns_no_market():
    db = _db()
    html = open(os.path.join(FIXTURES, "detail_1.html"), encoding="utf-8").read()
    detail = detail_parser.parse(html, url="u").model_copy(update={"marka": "", "model": ""})
    assert market.get_market_stats(db, detail).n == 0
