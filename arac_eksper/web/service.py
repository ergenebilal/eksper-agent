"""Panel ve /v1 API'nin ortak veri katmanı (tek kaynak: panel de Jeff de aynı fonksiyonları kullanır).
Salt okunur. Satıcı metni GÜVENSİZ girdidir: burada HTML üretilmez, yalnızca (metin, vurgulu_mu) parçaları döner."""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arac_eksper.collector import guard
from arac_eksper.config.settings import settings
from arac_eksper.storage import repo
from arac_eksper.storage.models import Event, FetchLog, Listing, ListingSnapshot, LLMCache, Verdict, Watch

ETIKETLER = ("ALINIR", "DUSUNULEBILIR", "ALINMAZ")
ALLOWED_URL_PREFIX = "https://www.sahibinden.com/"
MAX_LIST = 200


def _iso(dt):
    return guard.as_utc(dt).isoformat() if dt else None


def _latest_ids(db: Session):
    return select(func.max(Verdict.id)).group_by(Verdict.ilan_no)


def status(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    last_ok = db.query(FetchLog).filter(FetchLog.status == "OK").order_by(FetchLog.id.desc()).first()
    used = db.query(FetchLog).filter(FetchLog.timestamp >= now - timedelta(hours=1)).count()
    until = guard.is_blocked_now(db)
    latest = db.query(Verdict).filter(Verdict.id.in_(_latest_ids(db))).all()
    day_ago = now - timedelta(days=1)
    counts = {"alinir": 0, "dusunulebilir": 0, "alinmaz": 0}
    for v in latest:
        if not v.beklemede and v.created_at and guard.as_utc(v.created_at) >= day_ago:
            counts[v.etiket.lower()] += 1
    watches = []
    for w in db.query(Watch).order_by(Watch.id).all():
        last = (db.query(Event).filter(Event.type == "watch_run", Event.watch_id == w.id)
                .order_by(Event.id.desc()).first())
        watches.append({"id": w.id, "name": w.name, "active": bool(w.is_active), "interval_minutes": w.interval_minutes,
                        "active_hours": w.active_hours, "last_run_at": _iso(last.created_at) if last else None,
                        "last_status": (last.payload or {}).get("status") if last else None})
    return {"last_successful_fetch_at": _iso(last_ok.timestamp) if last_ok else None,
            "blocked_until": until.isoformat() if until else None,
            "pages_used_this_hour": used, "pages_limit": settings.max_pages_per_hour,
            "last_24h": counts, "llm_pending": sum(1 for v in latest if v.beklemede), "watchers": watches}


def _sapma(v: Verdict, fiyat: int):
    m = (v.piyasa or {}).get("medyan") or 0
    return round((fiyat - m) / m * 100, 1) if m > 0 else None


def listings(db: Session, etiket: str | None = None, q: str | None = None, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, MAX_LIST))
    query = (db.query(Verdict, Listing).join(Listing, Listing.ilan_no == Verdict.ilan_no)
             .filter(Verdict.id.in_(_latest_ids(db))))
    if etiket in ETIKETLER:                     # beyaz liste: serbest metin SQL'e gitmez
        query = query.filter(Verdict.etiket == etiket, Verdict.beklemede == False)  # noqa: E712
    if q:
        like = f"%{q[:60]}%"
        query = query.filter((Listing.baslik.ilike(like)) | (Listing.marka.ilike(like)) | (Listing.model.ilike(like)))
    order = {"ALINIR": 0, "DUSUNULEBILIR": 1, "ALINMAZ": 2}
    rows = query.all()
    rows.sort(key=lambda r: (r[0].beklemede, order.get(r[0].etiket, 3), -r[0].guven_skoru))
    return [{"ilan_no": l.ilan_no, "baslik": l.baslik, "marka": l.marka, "model": l.model, "seri": l.seri,
             "fiyat": l.fiyat, "yil": l.yil, "km": l.km, "il": l.il, "etiket": v.etiket, "beklemede": bool(v.beklemede),
             "skor": v.guven_skoru, "tamlik": v.veri_tamlik, "sapma_yuzde": _sapma(v, l.fiyat),
             "karar_zamani": _iso(v.created_at)} for v, l in rows[:limit]]


def highlight_segments(text: str, quotes: list[str]) -> list[tuple[str, bool]]:
    """Açıklamayı [(parça, vurgulu_mu)] olarak böler. Çıktı düz metindir; HTML değildir ve şablonda kaçışlanır."""
    spans = []
    for q in quotes:
        words = [re.escape(w) for w in (q or "").split()]
        if not words:
            continue
        for m in re.finditer(r"\s+".join(words), text, flags=re.IGNORECASE):
            spans.append((m.start(), m.end()))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out, pos = [], 0
    for a, b in merged:
        if a > pos:
            out.append((text[pos:a], False))
        out.append((text[a:b], True))
        pos = b
    if pos < len(text):
        out.append((text[pos:], False))
    return out or [(text, False)]


def safe_listing_url(url: str | None) -> str | None:
    """Toplanan URL güvensiz girdidir: yalnızca sahibinden https bağlantısı gösterilir (javascript: vb. düşer)."""
    if not url:
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", url) and not url.lower().startswith(("http://", "https://")):
        return None     # javascript:, data: vb. şemalar
    url = url if url.startswith("http") else "https://www.sahibinden.com" + (url if url.startswith("/") else "/" + url)
    return url if url.startswith(ALLOWED_URL_PREFIX) else None


def listing_detail(db: Session, ilan_no: str) -> dict | None:
    row = repo.latest_verdict_row(db, ilan_no)
    if not row or not row.detail_json:
        return None
    detail, findings = repo.row_to_inputs(row)
    verdict = repo.row_to_verdict(row)
    quotes = []
    if findings:
        for lst in (findings.olumlu_sinyaller, findings.olumsuz_sinyaller, findings.dolandiricilik_sinyalleri,
                    findings.belirsiz_ifadeler):
            quotes += [e.alinti for e in lst]
        quotes += [x for x in (findings.sase_alinti, findings.airbag_alinti, findings.motor_alinti,
                               findings.agir_hasar_alinti) if x]
    snaps = (db.query(ListingSnapshot).filter(ListingSnapshot.ilan_no == ilan_no)
             .order_by(ListingSnapshot.id).limit(200).all())
    return {
        "ilan_no": ilan_no, "detail": detail.model_dump(mode="json", exclude={"aciklama"}),
        "verdict": verdict.model_dump(mode="json"), "findings": findings.model_dump(mode="json") if findings else None,
        "aciklama_parcalari": highlight_segments(detail.aciklama or "", quotes),
        "fiyat_gecmisi": [{"fiyat": s.fiyat, "zaman": _iso(s.fetched_at)} for s in snaps],
        "ilan_url": safe_listing_url(detail.url), "karar_zamani": _iso(row.created_at),
    }


def events(db: Session, since: int = 0, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, MAX_LIST))
    rows = db.query(Event).filter(Event.id > since).order_by(Event.id.desc()).limit(limit).all()
    return [{"id": e.id, "type": e.type, "ilan_no": e.ilan_no, "watch_id": e.watch_id, "text": e.text,
             "delivered": bool(e.delivered), "created_at": _iso(e.created_at)} for e in rows]


def system(db: Session) -> dict:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    logs = db.query(FetchLog).order_by(FetchLog.id.desc()).limit(50).all()
    per = dict(db.query(FetchLog.status, func.count()).filter(FetchLog.timestamp >= day_ago.replace(tzinfo=None))
               .group_by(FetchLog.status).all())
    blocks = [{"zaman": _iso(l.timestamp)} for l in db.query(FetchLog).filter(FetchLog.status == "BLOCKED")
              .order_by(FetchLog.id.desc()).limit(20).all()]
    return {"fetch_loglari": [{"zaman": _iso(l.timestamp), "durum": l.status} for l in logs],   # URL gösterilmez
            "son_24_saat": per, "engel_gecmisi": blocks, "ardisik_engel": guard.consecutive_blocks(db),
            "llm_onbellek_kaydi": db.query(LLMCache).count(),
            "bildirim_modu": settings.notify_mode, "zamanlayici_modu": settings.scheduler_mode}
