"""Radar: bir watch için tek tur. SPEC §6.2.
Yalnızca 🟢 ALINIR bildirilir (yeni ilan, fiyat düşüşü sonrası yükselen ya da yeniden yayınlanan);
aynı ilan için aynı radarda ikinci bildirim gitmez."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from arac_eksper import pipeline
from arac_eksper.collector import guard
from arac_eksper.collector.lock import CollectionBusy, collection_lock
from arac_eksper.collector.url_builder import build_search_url
from arac_eksper.config.settings import settings
from arac_eksper.parser import list_parser
from arac_eksper.report import notifier
from arac_eksper.schemas import SearchCriteria
from arac_eksper.storage import repo
from arac_eksper.storage.models import Watch
from arac_eksper.watcher import diff


def in_active_hours(now: datetime, spec: str) -> bool:
    """'08:00-23:00' ya da gece yarısını aşan '22:00-06:00'."""
    try:
        start, end = spec.split("-")
    except ValueError:
        return True
    t = now.strftime("%H:%M")
    return start <= t <= end if start <= end else (t >= start or t <= end)


def maybe_notify(db: Session, watch: Watch, outcome: pipeline.EvalOutcome, reason: str,
                 result: pipeline.RunResult) -> None:
    v = outcome.verdict
    if v.beklemede or v.etiket != "ALINIR" or repo.already_notified(db, v.ilan_no, watch.id):
        return
    text = f"🎯 Radar «{watch.name}» — {reason}\n\n{pipeline.card_for(outcome)}"
    ev = notifier.emit(db, "alinir", text, ilan_no=v.ilan_no, watch_id=watch.id,
                       payload={"reason": reason, "verdict": v.model_dump(mode="json")}, feedback_buttons=True)
    repo.mark_notified(db, v.ilan_no, watch.id)
    result.events.append({"id": ev.id, "type": "alinir", "ilan_no": v.ilan_no, "text": text})


async def run_watch(db: Session, watch: Watch, collector, llm) -> pipeline.RunResult:
    result = pipeline.RunResult()
    criteria = SearchCriteria(**watch.criteria)

    until = guard.is_blocked_now(db)
    if until:  # engel beklemesi: hiçbir istek atılmaz, tekrar bildirim yok
        result.status = "BLOCKED"
        result.errors.append(f"engel beklemesi: {until.astimezone().strftime('%H:%M')} sonrasına kadar")
        return _finish(db, watch, result)

    try:
        with collection_lock():
            # LLM'e erişilemediği için bekleyen analizler: sayfa harcamadan yeniden dene
            for row in repo.pending_verdict_rows(db, limit=3):
                detail, _ = repo.row_to_inputs(row)
                try:
                    out = pipeline.evaluate_detail(db, llm, detail, criteria.max_butce)
                    result.outcomes.append(out)
                    maybe_notify(db, watch, out, "bekleyen analiz tamamlandı", result)
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"{detail.ilan_no}: {type(e).__name__}")

            res = await collector.fetch_list(build_search_url(criteria, page=1))
            result.pages_fetched += 1
            if res.status != "OK" or not res.html:
                pipeline.handle_fetch_problem(db, result, res, watch_id=watch.id)
                return _finish(db, watch, result)

            summaries, _ = list_parser.parse(res.html)
            changes = diff.detect_changes(db, summaries, criteria.marka, criteria.model)  # DB'ye yazmadan ÖNCE
            for s in summaries:
                repo.create_or_update_listing_summary(db, s, criteria.marka, criteria.model)

            candidates: List[tuple] = (
                [(s, "yeni ilan") for s in changes.new]
                + [(s, f"fiyat düştü: {old:,} → {new:,} TL".replace(",", ".")) for s, old, new in changes.price_drops]
                + [(s, f"yeniden yayın (eski ilan {old})") for s, old in changes.republished]
            )
            # Henüz hiç değerlendirilmemiş ilanlar (ilk tarama ya da tur başına limit yüzünden kalanlar):
            # "görüldü" diye işaretlenip unutulmasın, sonraki turlarda sırayla değerlendirilsin.
            listed = {s.ilan_no for s, _ in candidates}
            for s in summaries:
                if s.ilan_no not in listed and repo.latest_verdict_row(db, s.ilan_no) is None:
                    candidates.append((s, "ilk tarama / bekleyen ilan"))
            candidates = [(s, r) for s, r in candidates if pipeline.prefilter(s, criteria)]

            for s, reason in candidates[: settings.max_details_per_watch_run]:
                try:
                    out, problem = await pipeline.fetch_and_evaluate(db, collector, llm, s, criteria.marka,
                                                                     criteria.model, criteria.max_butce)
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"{s.ilan_no}: {type(e).__name__}")
                    continue
                if problem is not None:
                    result.pages_fetched += 1
                    if pipeline.handle_fetch_problem(db, result, problem, watch_id=watch.id):
                        break
                    continue
                if not out.reused:
                    result.pages_fetched += 1
                result.outcomes.append(out)
                maybe_notify(db, watch, out, reason, result)
    except CollectionBusy as e:
        result.status = "ERROR"
        result.errors.append(str(e))
    return _finish(db, watch, result)


def _finish(db: Session, watch: Watch, result: pipeline.RunResult) -> pipeline.RunResult:
    from datetime import timezone
    result.finished_at = datetime.now(timezone.utc)
    # Radarın GERÇEKTEN çalıştığının kanıtı: her tur events tablosuna yazılır (bildirim gönderilmez).
    repo.add_event(db, "watch_run", f"{watch.name}: {result.status}", watch_id=watch.id, payload={
        "watch": watch.name, "status": result.status, "pages": result.pages_fetched,
        "evaluated": len(result.outcomes), "alinir": result.counts["alinir"], "errors": result.errors[:5]})
    return result


def build_daily_summary(db: Session) -> str:
    from datetime import timedelta, timezone
    from arac_eksper.storage.models import FetchLog, Verdict as VerdictRow
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = db.query(VerdictRow).filter(VerdictRow.created_at >= since, VerdictRow.beklemede == False).all()  # noqa: E712
    c = {"ALINIR": 0, "DUSUNULEBILIR": 0, "ALINMAZ": 0}
    for r in rows:
        c[r.etiket] = c.get(r.etiket, 0) + 1
    blocks = db.query(FetchLog).filter(FetchLog.timestamp >= since, FetchLog.status == "BLOCKED").count()
    pages = db.query(FetchLog).filter(FetchLog.timestamp >= since, FetchLog.status == "OK").count()
    return (f"📊 Radar günlük özet (24 saat)\n🟢 {c['ALINIR']} · 🟡 {c['DUSUNULEBILIR']} · 🔴 {c['ALINMAZ']}\n"
            f"Çekilen sayfa: {pages} · Engel: {blocks}")
