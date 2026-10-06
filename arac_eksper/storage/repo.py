from sqlalchemy.orm import Session
from arac_eksper.storage import models
from arac_eksper import schemas

def get_listing(db: Session, ilan_no: str):
    return db.query(models.Listing).filter(models.Listing.ilan_no == ilan_no).first()

def create_or_update_listing(db: Session, detail: schemas.ListingDetail):
    db_listing = get_listing(db, detail.ilan_no)
    if not db_listing:
        db_listing = models.Listing(
            ilan_no=detail.ilan_no,
            url=detail.url,
            baslik=detail.baslik,
            fiyat=detail.fiyat,
            yil=detail.yil,
            km=detail.km,
            il=detail.il,
            ilce=detail.ilce,
            ilan_tarihi=detail.ilan_tarihi,
            seri=detail.seri,
            paket=detail.paket,
            vites=detail.vites,
            yakit=detail.yakit,
            kasa_tipi=detail.kasa_tipi,
            motor_hacmi=detail.motor_hacmi,
            renk=detail.renk,
            kimden=detail.kimden,
            agir_hasar_kayitli=detail.agir_hasar_kayitli,
            tramer_tutari_yapilandirilmis=detail.tramer_tutari_yapilandirilmis,
            aciklama=detail.aciklama,
            fetched_at=detail.fetched_at,
            raw_html_path=detail.raw_html_path
        )
        db.add(db_listing)
    else:
        # Fiyat değişmişse snapshot'a yazılabilir, şimdilik sadece fiyatı güncelleyelim.
        db_listing.fiyat = detail.fiyat
        db_listing.fetched_at = detail.fetched_at

    db.commit()

def create_or_update_listing_summary(db: Session, summary, marka: str, model: str):
    from arac_eksper.storage.models import Listing, ListingSnapshot
    from datetime import datetime, timezone
    
    db_listing = db.query(Listing).filter(Listing.ilan_no == summary.ilan_no).first()
    now_utc = datetime.now(timezone.utc)
    
    if not db_listing:
        db_listing = Listing(
            ilan_no=summary.ilan_no,
            url=summary.url,
            baslik=summary.baslik,
            marka=marka,
            model=model,
            seri=getattr(summary, 'seri', None),
            fiyat=summary.fiyat,
            yil=summary.yil,
            km=summary.km,
            il=summary.il,
            ilce=summary.ilce,
            ilan_tarihi=summary.ilan_tarihi,
            source="list",
            fetched_at=now_utc,
            aciklama=""
        )
        db.add(db_listing)
    else:
        # Fiyat güncellendiyse list'ten de gelse güncelle
        if db_listing.fiyat != summary.fiyat:
            db_listing.fiyat = summary.fiyat
            db_listing.fetched_at = now_utc
            
    snapshot = ListingSnapshot(
        ilan_no=summary.ilan_no,
        fiyat=summary.fiyat,
        fetched_at=now_utc
    )
    db.add(snapshot)
    db.commit()
    db.refresh(db_listing)
    return db_listing
