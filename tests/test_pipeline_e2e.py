import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from arac_eksper import pipeline
from arac_eksper.config.settings import settings
from arac_eksper.schemas import SearchCriteria
from arac_eksper.storage import repo
from arac_eksper.storage.models import Base, Event, FetchLog, Watch
from tests.helpers import FakeCollector, FakeLLM, DownLLM, list_html, detail_html, ok, blocked

CRIT = SearchCriteria(marka="Renault", model="Megane", max_butce=1_000_000, min_yil=2020)
# 7 emsal ~900k + hedef 820k (ilk sırada)
ITEMS = [("1001", 820_000, "Temiz Megane")] + [(f"20{i:02d}", 900_000 + i * 2_000, "Megane") for i in range(7)]


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def run(coro):
    return asyncio.run(coro)


def test_search_end_to_end_green_with_offer_below_asking(db):
    col = FakeCollector([ok(list_html(ITEMS))], {"1001": ok(detail_html("1001", 820_000))})
    res = run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1, max_details=1))
    assert res.status == "OK" and len(res.outcomes) == 1
    v = res.outcomes[0].verdict
    assert v.etiket == "ALINIR", (v.etiket, v.guven_skoru, v.hard_fails, v.piyasa)
    assert v.piyasa.n >= 7 and v.tavsiye_teklif and v.tavsiye_teklif <= 820_000 and v.ust_sinir <= 820_000
    assert v.trace, "explain için karar dökümü olmalı"
    # karar kaydedilmiş ve report/explain için yeniden üretilebilir
    row = repo.latest_verdict_row(db, "1001")
    detail, findings = repo.row_to_inputs(row)
    assert detail.ilan_no == "1001" and findings is not None
    assert "ALINIR" in pipeline.card_for(res.outcomes[0])
    js = res.to_json_dict()
    assert js["status"] == "OK" and js["counts"]["alinir"] == 1 and js["results"][0]["ilan_no"] == "1001"


def test_second_search_reuses_recent_verdict_without_refetch(db):
    col = FakeCollector([ok(list_html(ITEMS))], {"1001": ok(detail_html("1001", 820_000))})
    run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1, max_details=1))
    assert col.detail_calls == ["1001"]
    run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1, max_details=1))
    assert col.detail_calls == ["1001"], "fiyat değişmediyse detay sayfası yeniden çekilmemeli"


def test_blocked_list_stops_everything_and_emits_one_event(db):
    col = FakeCollector([blocked()])
    res = run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=2, max_details=3))
    assert res.status == "BLOCKED" and not res.outcomes and col.detail_calls == []
    assert col.list_calls == 1, "engelden sonra ikinci sayfa denenmemeli"
    assert db.query(Event).filter_by(type="blocked").count() == 1
    assert res.to_json_dict()["status"] == "BLOCKED"


def test_block_mid_details_keeps_partial_results_and_stops(db):
    items = [("1001", 820_000, "A"), ("1002", 830_000, "B"), ("1003", 840_000, "C")] + ITEMS[1:]
    col = FakeCollector([ok(list_html(items))],
                        {"1001": ok(detail_html("1001", 820_000)), "1002": blocked(), "1003": ok(detail_html("1003", 840_000))})
    res = run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1, max_details=3))
    assert res.status == "BLOCKED" and len(res.outcomes) == 1
    assert col.detail_calls == ["1001", "1002"], "blok sonrası 3. detay denenmemeli"


def test_backoff_wait_does_not_spam_events(db):
    col = FakeCollector([blocked("engel beklemesi: 14:00 sonrasına kadar")])
    run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1))
    assert db.query(Event).filter_by(type="blocked").count() == 0


def test_llm_down_marks_pending_never_green_and_prefilter_applies(db):
    col = FakeCollector([ok(list_html(ITEMS))], {"1001": ok(detail_html("1001", 820_000))})
    res = run(pipeline.run_search(db, col, DownLLM(), CRIT, pages=1, max_details=1))
    v = res.outcomes[0].verdict
    assert v.beklemede and v.etiket != "ALINIR" and res.counts["beklemede"] == 1
    assert [r.ilan_no for r in repo.pending_verdict_rows(db)] == ["1001"]


def test_prefilter_skips_over_budget_and_high_km(db):
    over = ("3001", 1_500_000, "Pahalı")
    col = FakeCollector([ok(list_html([over] + ITEMS))], {"1001": ok(detail_html("1001", 820_000))})
    run(pipeline.run_search(db, col, FakeLLM(), CRIT, pages=1, max_details=2))
    assert "3001" not in col.detail_calls


def test_connection_error_and_invalid_json_become_pending_not_exception(tmp_path):
    """K3: LLM bağlantı/şema hatası 'beklemede' karar üretir; ilan temiz görünmez, sayfa yeniden çekilmez."""
    import pytest
    from datetime import datetime, timezone, date
    from pydantic import ValidationError
    from arac_eksper import pipeline
    from arac_eksper.llm.client import LLMUnavailable
    from arac_eksper.schemas import ListingDetail, DescriptionFindings
    from arac_eksper.storage import repo
    from arac_eksper.storage.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    d = ListingDetail(ilan_no="9", url="u", baslik="b", marka="Renault", model="Megane", fiyat=1, yil=2022, km=1,
                      il="x", ilan_tarihi=date.today(), aciklama="a", fetched_at=datetime.now(timezone.utc))
    repo.create_or_update_listing(db, d)

    class BadJSON:
        def parse_structured(self, *a, **k):
            try:
                DescriptionFindings.model_validate_json("{}")
            except ValidationError as e:
                raise e
    for llm in (BadJSON(),):
        out = pipeline.evaluate_detail(db, llm, d, None)
        assert out.verdict.beklemede and out.verdict.etiket == "DUSUNULEBILIR"
