"""Toplama → ayrıştırma → analiz → karar hattı. CLI (search), radar (watch) ve ileride HTTP API bunu paylaşır.
Karar mantığı rules_engine'dedir; burada yalnızca akış ve hata/engel yönetimi vardır."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from arac_eksper.analysis import description_llm, market, rules_engine
from arac_eksper.collector import guard
from arac_eksper.collector.base import FetchResult
from arac_eksper.collector.lock import CollectionBusy, collection_lock
from arac_eksper.collector.url_builder import build_search_url
from arac_eksper.config.settings import settings
from arac_eksper.llm.client import LLMUnavailable
from arac_eksper.parser import detail_parser, list_parser
from arac_eksper.report import notifier
from arac_eksper.report.card import generate_markdown_card
from arac_eksper.schemas import (DescriptionFindings, ListingDetail, ListingSummary, SearchCriteria, Verdict)
from arac_eksper.storage import repo

BASE_URL = "https://www.sahibinden.com"
REUSE_HOURS = 24


@dataclass
class EvalOutcome:
    detail: ListingDetail
    findings: Optional[DescriptionFindings]
    verdict: Verdict
    reused: bool = False


@dataclass
class RunResult:
    status: str = "OK"          # OK | BLOCKED | ERROR
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    pages_fetched: int = 0
    outcomes: List[EvalOutcome] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    events: List[dict] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def counts(self) -> dict:
        c = {"alinir": 0, "dusunulebilir": 0, "alinmaz": 0, "beklemede": 0}
        for o in self.outcomes:
            if o.verdict.beklemede:
                c["beklemede"] += 1
            else:
                c[o.verdict.etiket.lower()] += 1
        return c

    def to_json_dict(self) -> dict:
        return {
            "status": self.status, "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.finished_at or datetime.now(timezone.utc)).isoformat(),
            "pages_fetched": self.pages_fetched,
            "results": [o.verdict.model_dump(mode="json") for o in ranked(self.outcomes)],
            "counts": self.counts, "errors": self.errors, "events": self.events,
        }


def ranked(outcomes: List[EvalOutcome]) -> List[EvalOutcome]:
    order = {"ALINIR": 0, "DUSUNULEBILIR": 1, "ALINMAZ": 2}
    return sorted(outcomes, key=lambda o: (order[o.verdict.etiket], -o.verdict.guven_skoru))


def abs_url(url: str) -> str:
    return url if url.startswith("http") else BASE_URL + url


def prefilter(s: ListingSummary, criteria: SearchCriteria) -> bool:
    """Liste düzeyinde ön eleme (detay sayfası isteği harcamadan). True = devam."""
    if s.fiyat > criteria.max_butce:
        return False
    if criteria.min_butce and s.fiyat < criteria.min_butce:
        return False
    if criteria.min_yil and s.yil < criteria.min_yil:
        return False
    if criteria.max_km and s.km > criteria.max_km:
        return False
    max_yillik = rules_engine.load_rules()["hard_fails"]["max_yillik_km"]
    yas = max(datetime.now(timezone.utc).year - s.yil, 1)
    return s.km / yas <= max_yillik


def pending_outcome(detail: ListingDetail) -> Verdict:
    return Verdict(ilan_no=detail.ilan_no, etiket="DUSUNULEBILIR", guven_skoru=0.0, veri_tamlik=0.0,
                   eksiler=["LLM analizi bekliyor (havuza erişilemedi)"], beklemede=True,
                   ekspertiz_kontrol_listesi=[])


def evaluate_detail(db: Session, llm, detail: ListingDetail, max_butce: Optional[int]) -> EvalOutcome:
    """LLM bulgusu + piyasa + kural motoru. LLM erişilemezse 'beklemede' kararı üretilir
    (sessizce 'bulgu yok' DÖNMEZ — ilan yanlışlıkla temiz görünmesin)."""
    try:
        findings = description_llm.analyze_description(llm, detail.baslik, detail.aciklama,
                                                       db=db, ilan_no=detail.ilan_no)
    except LLMUnavailable:
        verdict = pending_outcome(detail)
        repo.save_verdict(db, verdict, detail, None)
        return EvalOutcome(detail, None, verdict)
    stats = market.get_market_stats(db, detail)
    verdict = rules_engine.determine_verdict(detail, findings, stats, max_butce=max_butce)
    repo.save_verdict(db, verdict, detail, findings)
    return EvalOutcome(detail, findings, verdict)


def reuse_recent(db: Session, s: ListingSummary) -> Optional[EvalOutcome]:
    """Fiyatı değişmemiş ve son 24 saatte değerlendirilmiş ilan için sayfa/LLM harcamadan eski karar."""
    row = repo.latest_verdict_row(db, s.ilan_no)
    if not row or row.beklemede or not row.detail_json:
        return None
    created = guard.as_utc(row.created_at) if row.created_at else None
    if not created or datetime.now(timezone.utc) - created > timedelta(hours=REUSE_HOURS):
        return None
    detail, findings = repo.row_to_inputs(row)
    if detail.fiyat != s.fiyat:
        return None
    return EvalOutcome(detail, findings, repo.row_to_verdict(row), reused=True)


async def fetch_and_evaluate(db: Session, collector, llm, s: ListingSummary, marka: str, model: str,
                             max_butce: Optional[int]) -> tuple[Optional[EvalOutcome], Optional[FetchResult]]:
    """(sonuç, None) ya da engel/limit/hata durumunda (None, fetch_sonucu)."""
    reused = reuse_recent(db, s)
    if reused:
        return reused, None
    res = await collector.fetch_detail(abs_url(s.url))
    if res.status != "OK" or not res.html:
        return None, res
    try:
        detail = detail_parser.parse(res.html, url=abs_url(s.url))
    except Exception as e:  # noqa: BLE001  (DOM değişti / beklenmeyen sayfa)
        return None, FetchResult(status="ERROR", final_url=s.url, note=f"parse hatası ({s.ilan_no}): {type(e).__name__}")
    detail.raw_html_path = res.saved_path
    detail.marka = detail.marka or marka
    detail.model = detail.model or model
    repo.create_or_update_listing(db, detail)
    return evaluate_detail(db, llm, detail, max_butce), None


def handle_fetch_problem(db: Session, result: RunResult, res: FetchResult, watch_id: Optional[int] = None) -> bool:
    """Engel/limit/hata durumunu RunResult'a işler. True = toplama DURMALI."""
    if res.status == "BLOCKED":
        result.status = "BLOCKED"
        result.errors.append(res.note or "engel")
        fresh = not (res.note or "").startswith("engel beklemesi")   # bekleme süresindeki reddetmelerde tekrar bildirme
        if fresh:
            ev = notifier.emit(db, "blocked", notifier.blocked_text(res.note), watch_id=watch_id)
            result.events.append({"id": ev.id, "type": "blocked", "text": ev.text})
            if guard.pause_watches_if_needed(db):
                ev2 = notifier.emit(db, "watch_paused",
                                    f"⏸ Ardışık {settings.watch_pause_after_blocks} engel: radarlar duraklatıldı. "
                                    "Manuel kontrol sonrası `arac watch resume` ile başlat.", watch_id=watch_id)
                result.events.append({"id": ev2.id, "type": "watch_paused", "text": ev2.text})
        return True
    if res.status == "RATE_LIMITED":
        result.errors.append(res.note or "saatlik limit")
        return True
    if res.status == "NOT_FOUND":
        result.errors.append(f"ilan bulunamadı: {res.final_url}")
        return False
    result.errors.append(res.note or "hata")
    if result.status == "OK" and res.status == "ERROR" and "tarayıcı" in (res.note or ""):
        result.status = "ERROR"
        return True
    return False


async def run_search(db: Session, collector, llm, criteria: SearchCriteria,
                     pages: Optional[int] = None, max_details: Optional[int] = None) -> RunResult:
    """Anlık arama: SPEC §6.1."""
    result = RunResult()
    pages = pages or settings.search_pages
    max_details = max_details or settings.max_details_per_search
    try:
        with collection_lock():
            summaries: List[ListingSummary] = []
            for page in range(1, pages + 1):
                res = await collector.fetch_list(build_search_url(criteria, page=page))
                result.pages_fetched += 1
                if res.status != "OK" or not res.html:
                    handle_fetch_problem(db, result, res)
                    break
                page_items, _ = list_parser.parse(res.html)
                summaries.extend(page_items)
                for s in page_items:
                    repo.create_or_update_listing_summary(db, s, criteria.marka, criteria.model)
                if not page_items:
                    break

            if result.status == "OK":
                candidates = [s for s in summaries if prefilter(s, criteria)]
                seen = set()
                for s in candidates[:max_details]:
                    if s.ilan_no in seen:
                        continue
                    seen.add(s.ilan_no)
                    try:
                        outcome, problem = await fetch_and_evaluate(db, collector, llm, s, criteria.marka,
                                                                    criteria.model, criteria.max_butce)
                    except Exception as e:  # noqa: BLE001
                        result.errors.append(f"{s.ilan_no}: {type(e).__name__}: {e}")
                        continue
                    if problem is not None:
                        result.pages_fetched += 1
                        if handle_fetch_problem(db, result, problem):
                            break
                        continue
                    if not outcome.reused:
                        result.pages_fetched += 1
                    result.outcomes.append(outcome)
    except CollectionBusy as e:
        result.status = "ERROR"
        result.errors.append(str(e))
    result.finished_at = datetime.now(timezone.utc)
    return result


def card_for(outcome: EvalOutcome) -> str:
    return generate_markdown_card(outcome.detail, outcome.findings, outcome.verdict)
