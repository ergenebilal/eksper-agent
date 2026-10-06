"""Eksik/bozuk veri 'iyi' sayılmaz; hata metni sızmaz; SQLite eşzamanlılığı."""
import re
import pytest
from arac_eksper.parser import detail_parser
from arac_eksper.analysis.rules_engine import determine_verdict
from arac_eksper.schemas import MarketStats
from tests.helpers import detail_html
from tests.test_hard_fails import _detail, _findings


def test_missing_damage_field_is_unknown_not_no():
    html = detail_html("123456", 800000).replace('Ağır Hasar Kayıtlı', 'Başka Alan')
    assert detail_parser.parse(html, url="u").agir_hasar_kayitli is None
    assert detail_parser.parse(detail_html("123456", 800000), url="u").agir_hasar_kayitli is False


@pytest.mark.parametrize("label", ["Yıl", "KM"])
def test_unreadable_year_or_km_fails_the_parse(label):
    html = detail_html("123456", 800000).replace(f'<dt>{label}</dt><dd>',
                                                 f'<dt>{label}</dt><dd>?')
    with pytest.raises(ValueError):
        detail_parser.parse(html, url="u")


def test_price_hard_fail_needs_enough_comparables():
    few = MarketStats(n=2, medyan=500000, p25=490000, p75=510000, guven="dusuk")
    v = determine_verdict(_detail(fiyat=900000), _findings(), few)      # %80 pahalı ama n=2
    assert not any("piyasanın" in h for h in v.hard_fails) and v.etiket != "ALINIR"
    many = MarketStats(n=12, medyan=500000, p25=490000, p75=510000, guven="yuksek")
    assert any("piyasanın" in h for h in determine_verdict(_detail(fiyat=900000), _findings(), many).hard_fails)


def test_sqlite_uses_wal_and_busy_timeout(tmp_path):
    from sqlalchemy import create_engine, text
    from arac_eksper.storage import db as dbmod
    eng = create_engine(f"sqlite:///{tmp_path/'w.db'}")
    from sqlalchemy import event
    event.listen(eng, "connect", dbmod._sqlite_pragmas)
    with eng.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 30000


def test_error_lists_never_carry_exception_text():
    src = open("arac_eksper/pipeline.py", encoding="utf-8").read() + open("arac_eksper/watcher/runner.py", encoding="utf-8").read()
    assert not re.search(r"type\(e\)\.__name__\}: \{e\}", src)
