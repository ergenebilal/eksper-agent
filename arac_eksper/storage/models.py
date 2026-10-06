from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Float, Date, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from arac_eksper.storage.db import Base

class Listing(Base):
    __tablename__ = "listings"

    ilan_no = Column(String, primary_key=True, index=True)
    url = Column(String, nullable=False)
    baslik = Column(String, nullable=False)
    fiyat = Column(Integer, nullable=False)
    yil = Column(Integer, nullable=False)
    km = Column(Integer, nullable=False)
    il = Column(String, nullable=False)
    ilce = Column(String, nullable=True)
    ilan_tarihi = Column(Date, nullable=False)
    
    seri = Column(String, nullable=True)
    paket = Column(String, nullable=True)
    vites = Column(String, nullable=True)
    yakit = Column(String, nullable=True)
    kasa_tipi = Column(String, nullable=True)
    motor_hacmi = Column(String, nullable=True)
    renk = Column(String, nullable=True)
    kimden = Column(String, nullable=True)
    
    agir_hasar_kayitli = Column(Boolean, nullable=True)
    tramer_tutari_yapilandirilmis = Column(Integer, nullable=True)
    aciklama = Column(Text, nullable=False)
    
    fetched_at = Column(DateTime, default=datetime.utcnow)
    raw_html_path = Column(String, nullable=True)

    snapshots = relationship("ListingSnapshot", back_populates="listing", cascade="all, delete-orphan")
    parts = relationship("Part", back_populates="listing", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="listing", cascade="all, delete-orphan")
    verdicts = relationship("Verdict", back_populates="listing", cascade="all, delete-orphan")


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, ForeignKey("listings.ilan_no"), nullable=False)
    fiyat = Column(Integer, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    listing = relationship("Listing", back_populates="snapshots")


class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, ForeignKey("listings.ilan_no"), nullable=False)
    name = Column(String, nullable=False)
    state = Column(String, nullable=False)  # ORIGINAL, LOCAL_PAINT, vs.

    listing = relationship("Listing", back_populates="parts")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, ForeignKey("listings.ilan_no"), nullable=False)
    type = Column(String, nullable=False)  # tramer, sase_islem, olumlu_sinyal vb.
    value = Column(String, nullable=True)
    alinti = Column(String, nullable=True)

    listing = relationship("Listing", back_populates="findings")


class Verdict(Base):
    __tablename__ = "verdicts"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, ForeignKey("listings.ilan_no"), nullable=False)
    etiket = Column(String, nullable=False)  # ALINIR, DUSUNULEBILIR, ALINMAZ
    guven_skoru = Column(Float, nullable=False)
    veri_tamlik = Column(Float, nullable=False)
    
    hard_fails = Column(JSON, nullable=True)
    artilar = Column(JSON, nullable=True)
    eksiler = Column(JSON, nullable=True)
    tavsiye_teklif = Column(Integer, nullable=True)
    ekspertiz_kontrol_listesi = Column(JSON, nullable=True)

    listing = relationship("Listing", back_populates="verdicts")


class MarketCache(Base):
    __tablename__ = "market_cache"

    id = Column(Integer, primary_key=True, index=True)
    hash = Column(String, unique=True, index=True, nullable=False)
    n = Column(Integer, nullable=False)
    medyan = Column(Integer, nullable=False)
    p25 = Column(Integer, nullable=False)
    p75 = Column(Integer, nullable=False)
    guven = Column(String, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class Watch(Base):
    __tablename__ = "watches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    criteria = Column(JSON, nullable=False)
    interval_minutes = Column(Integer, default=30)
    active_hours = Column(String, default="00:00-23:59")
    is_active = Column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, nullable=False)
    watch_id = Column(Integer, ForeignKey("watches.id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)


class FetchLog(Base):
    __tablename__ = "fetch_logs"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    status = Column(String, nullable=False) # OK, BLOCKED, NOT_FOUND, ERROR
    timestamp = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    ilan_no = Column(String, nullable=False)
    is_positive = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
