import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.collector import playwright_collector
from arac_eksper.llm import client as llm_client
from arac_eksper.storage.models import Base, Event, FetchLog, Watch
from tests.helpers import FakeCollector, FakeLLM, list_html, detail_html, ok, blocked

runner = CliRunner()
ITEMS = [("1001", 820_000, "Temiz Megane")] + [(f"20{i:02d}", 900_000 + i * 2_000, "Megane") for i in range(7)]
SEARCH = ["search", "--marka", "Renault", "--model", "Megane", "--max-butce", "1000000",
          "--min-yil", "2020", "--pages", "1", "--max-detay", "1"]


@pytest.fixture
def env(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(cli, "_session", lambda: Session())
    monkeypatch.setattr(llm_client, "OpenAIClient", lambda: FakeLLM())
    return Session


def use_collector(monkeypatch, collector):
    monkeypatch.setattr(playwright_collector, "PlaywrightCollector", lambda db: collector)


def test_search_json_stdout_is_pure_json_and_exit_0(env, monkeypatch):
    use_collector(monkeypatch, FakeCollector([ok(list_html(ITEMS))], {"1001": ok(detail_html("1001", 820_000))}))
    r = runner.invoke(cli.app, SEARCH + ["--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)            # stdout yalnızca JSON olmalı
    assert data["status"] == "OK" and data["counts"]["alinir"] == 1
    assert data["results"][0]["ilan_no"] == "1001" and data["results"][0]["tavsiye_teklif"] <= 820_000
    assert {"run_id", "started_at", "finished_at", "pages_fetched", "errors", "events"} <= data.keys()


def test_search_blocked_exit_code_2(env, monkeypatch):
    use_collector(monkeypatch, FakeCollector([blocked()]))
    r = runner.invoke(cli.app, SEARCH + ["--json"])
    assert r.exit_code == 2
    assert json.loads(r.stdout)["status"] == "BLOCKED"


def test_search_bad_criteria_exit_3(env):
    r = runner.invoke(cli.app, SEARCH + ["--vites", "uzay_vitesi", "--json"])
    assert r.exit_code == 3


def test_search_unknown_category_exit_3(env):
    r = runner.invoke(cli.app, ["search", "--marka", "Fiat", "--model", "Egea", "--max-butce", "500000", "--json"])
    assert r.exit_code == 3


def test_text_mode_prints_card_and_report_explain_work_after(env, monkeypatch):
    use_collector(monkeypatch, FakeCollector([ok(list_html(ITEMS))], {"1001": ok(detail_html("1001", 820_000))}))
    r = runner.invoke(cli.app, SEARCH)
    assert r.exit_code == 0 and "ALINIR" in r.stdout and "Teklif" in r.stdout
    rep = runner.invoke(cli.app, ["report", "1001"])
    assert rep.exit_code == 0 and "ALINIR" in rep.stdout and "ekspertiz" in rep.stdout.lower()
    rj = runner.invoke(cli.app, ["report", "1001", "--json"])
    assert json.loads(rj.stdout)["etiket"] == "ALINIR"
    ex = runner.invoke(cli.app, ["explain", "1001"])
    assert ex.exit_code == 0 and "Puan dökümü" in ex.stdout and "başlangıç" in ex.stdout


def test_report_unknown_listing_exit_1(env):
    assert runner.invoke(cli.app, ["report", "yok"]).exit_code == 1
    assert runner.invoke(cli.app, ["explain", "yok"]).exit_code == 1


def test_watch_add_list_pause_resume(env):
    r = runner.invoke(cli.app, ["watch", "add", "--name", "w1", "--marka", "Renault", "--model", "Megane",
                                "--max-butce", "900000", "--interval", "5"])
    assert r.exit_code == 0 and "her 15 dk" in r.stdout        # minimum 15 dk zorlanır
    assert "AKTİF" in runner.invoke(cli.app, ["watch", "list"]).stdout
    runner.invoke(cli.app, ["watch", "pause", "w1"])
    assert "DURDU" in runner.invoke(cli.app, ["watch", "list"]).stdout
    runner.invoke(cli.app, ["watch", "resume"])
    assert "AKTİF" in runner.invoke(cli.app, ["watch", "list"]).stdout


def test_events_and_status_json(env):
    s = env()
    s.add(Event(type="alinir", text="x", ilan_no="1")); s.add(Event(type="watch_run", text="r", watch_id=1, payload={"status": "OK"}))
    s.add(Watch(name="w", criteria={})); s.add(FetchLog(url="u", status="OK")); s.commit()
    ev = json.loads(runner.invoke(cli.app, ["events", "--since", "0"]).stdout)
    assert [e["type"] for e in ev["events"]] == ["alinir"] and ev["last_id"] == 1     # watch_run bildirim değil
    assert json.loads(runner.invoke(cli.app, ["events", "--since", "1"]).stdout)["events"] == []
    st = json.loads(runner.invoke(cli.app, ["status", "--json"]).stdout)
    assert st["last_successful_fetch_at"] and st["blocked_until"] is None
    assert st["watchers"][0]["last_status"] == "OK"


def test_feedback_command(env):
    assert runner.invoke(cli.app, ["feedback", "1001", "pos"]).exit_code == 0
    assert runner.invoke(cli.app, ["feedback", "1001", "belki"]).exit_code == 3
