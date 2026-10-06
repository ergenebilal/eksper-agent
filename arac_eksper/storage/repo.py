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
    db.refresh(db_listing)
    return db_listing
