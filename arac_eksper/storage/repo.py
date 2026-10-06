from sqlalchemy.orm import Session
from arac_eksper.storage import models
from arac_eksper import schemas

def get_listing(db: Session, ilan_no: str):
    return db.query(models.Listing).filter(models.Listing.ilan_no == ilan_no).first()

DETAIL_FIELDS = [
    "url", "baslik", "fiyat", "yil", "km", "il", "ilce", "ilan_tarihi",
    "seri", "paket", "vites", "yakit", "kasa_tipi", "motor_hacmi", "renk", "kimden",
    "agir_hasar_kayitli", "tramer_tutari_yapilandirilmis", "aciklama", "fetched_at", "raw_html_path",
]

def create_or_update_listing(db: Session, detail: schemas.ListingDetail):
    db_listing = get_listing(db, detail.ilan_no)
    if not db_listing:
        db_listing = models.Listing(ilan_no=detail.ilan_no, marka=detail.marka or "", model=detail.model or "", source="detail")
        for f in DETAIL_FIELDS:
            setattr(db_listing, f, getattr(detail, f))
        db.add(db_listing)
    else:
        # Liste kaydı detayla zenginleşir: vites/yakıt/açıklama vb. detaydan gelir.
        for f in DETAIL_FIELDS:
            setattr(db_listing, f, getattr(detail, f))
        if detail.marka:
            db_listing.marka = detail.marka
        if detail.model:
            db_listing.model = detail.model
        db_listing.source = "detail"

    db.commit()
    db.refresh(db_listing)
    return db_listing

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
        # fetched_at = "son görülme": ilan listede durdukça taze kalır (piyasa 30 gün penceresi için)
        db_listing.fetched_at = now_utc
            
    last = (db.query(ListingSnapshot).filter(ListingSnapshot.ilan_no == summary.ilan_no)
            .order_by(ListingSnapshot.id.desc()).first())
    if last is None or last.fiyat != summary.fiyat:     # aynı fiyatı her görüşte tekrar yazma (şişme)
        db.add(ListingSnapshot(ilan_no=summary.ilan_no, fiyat=summary.fiyat, fetched_at=now_utc))
    db.commit()
    db.refresh(db_listing)
    return db_listing


# ---------- Verdict / rapor ----------
def save_verdict(db: Session, verdict: schemas.Verdict, detail: schemas.ListingDetail, findings):
    """Kararı, girdisiyle (detail+findings) birlikte kaydeder: report/explain bunu yeniden üretir."""
    row = models.Verdict(
        ilan_no=verdict.ilan_no, etiket=verdict.etiket, guven_skoru=verdict.guven_skoru,
        veri_tamlik=verdict.veri_tamlik, hard_fails=verdict.hard_fails, artilar=verdict.artilar,
        eksiler=verdict.eksiler, tavsiye_teklif=verdict.tavsiye_teklif, ust_sinir=verdict.ust_sinir,
        ekspertiz_kontrol_listesi=verdict.ekspertiz_kontrol_listesi, trace=verdict.trace,
        piyasa=verdict.piyasa.model_dump() if verdict.piyasa else None,
        beklemede=verdict.beklemede,
        detail_json=detail.model_dump(mode="json"),
        findings_json=findings.model_dump(mode="json") if findings else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_verdict_row(db: Session, ilan_no: str):
    return (db.query(models.Verdict).filter(models.Verdict.ilan_no == ilan_no)
            .order_by(models.Verdict.id.desc()).first())


def row_to_verdict(row) -> schemas.Verdict:
    return schemas.Verdict(
        ilan_no=row.ilan_no, etiket=row.etiket, guven_skoru=row.guven_skoru, veri_tamlik=row.veri_tamlik,
        hard_fails=row.hard_fails or [], artilar=row.artilar or [], eksiler=row.eksiler or [],
        piyasa=schemas.MarketStats(**row.piyasa) if row.piyasa else None,
        tavsiye_teklif=row.tavsiye_teklif, ust_sinir=row.ust_sinir,
        ekspertiz_kontrol_listesi=row.ekspertiz_kontrol_listesi or [], trace=row.trace or [],
        beklemede=bool(row.beklemede),
    )


def row_to_inputs(row):
    detail = schemas.ListingDetail.model_validate(row.detail_json)
    findings = schemas.DescriptionFindings.model_validate(row.findings_json) if row.findings_json else None
    return detail, findings


def pending_verdict_rows(db: Session, limit: int = 3):
    """LLM erişilemediği için analizi bekleyen ilanlar (her ilanın son kararı beklemede olanlar)."""
    latest = {}
    for r in db.query(models.Verdict).order_by(models.Verdict.id.asc()).all():
        latest[r.ilan_no] = r
    return [r for r in latest.values() if r.beklemede][:limit]


# ---------- Bildirim olayları / geri bildirim ----------
def add_event(db: Session, type_: str, text: str, ilan_no: str | None = None,
              watch_id: int | None = None, payload: dict | None = None):
    ev = models.Event(type=type_, text=text, ilan_no=ilan_no, watch_id=watch_id, payload=payload)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def already_notified(db: Session, ilan_no: str, watch_id: int) -> bool:
    return db.query(models.Notification).filter_by(ilan_no=ilan_no, watch_id=watch_id).first() is not None


def mark_notified(db: Session, ilan_no: str, watch_id: int):
    db.add(models.Notification(ilan_no=ilan_no, watch_id=watch_id))
    db.commit()


def add_feedback(db: Session, ilan_no: str, positive: bool):
    db.add(models.Feedback(ilan_no=ilan_no, is_positive=positive))
    db.commit()
