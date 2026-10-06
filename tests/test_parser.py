"""R0.4: Python ayrıştırıcı (kişisel araç) gerçek sayfa yapısında. Gerçek fixture'lar (tests/fixtures/real) ile alan
doğruluğu; sentetik sayfalar aynı yapıda üretilir (tests/helpers.py)."""
import os
import pathlib

import pytest

from arac_eksper.parser import detail_parser, list_parser
from tests.test_real_pages import expected

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
REAL = pathlib.Path(FIXTURES_DIR) / "real"


def test_list_parser():
    with open(os.path.join(FIXTURES_DIR, "list_1.html"), "r", encoding="utf-8") as f:
        listings, next_page = list_parser.parse(f.read())
    assert len(listings) == 2
    assert listings[0].ilan_no == "123456789" and listings[0].fiyat == 850000 and listings[0].km == 60000
    assert (listings[0].marka, listings[0].model, listings[0].il, listings[0].ilce) == ("Renault", "Megane", "Bursa", "Nilüfer")
    assert next_page == "/arama?page=2"


def test_detail_parser():
    with open(os.path.join(FIXTURES_DIR, "detail_1.html"), "r", encoding="utf-8") as f:
        detail = detail_parser.parse(f.read(), url="http://test", il="İstanbul", ilce="Kadıköy")
    assert detail.ilan_no == "123456789" and detail.fiyat == 850000 and detail.yil == 2018 and detail.km == 95000
    assert detail.vites == "Otomatik" and detail.yakit == "Dizel" and detail.agir_hasar_kayitli is False
    assert "Aracım temizdir" in detail.aciklama and detail.il == "İstanbul"
    assert detail.parts["motor_kaputu"] == "degisen" and detail.parts["tavan"] == "orijinal"


@pytest.mark.parametrize("path", sorted(REAL.glob("detail_*.html")), ids=lambda p: p.stem)
def test_real_detail_pages_match_independent_reading(path):
    html = path.read_text(encoding="utf-8")
    d, e = detail_parser.parse(html, url="u"), expected(path)
    assert d.ilan_no == e["ilan_no"] and d.yil == e["yil"] and d.km == e["km"]
    assert (d.marka, d.seri, d.paket, d.vites, d.yakit) == (e["marka"], e["seri"], e["paket"], e["vites"], e["yakit"])
    assert d.agir_hasar_kayitli is e["agir"]
    assert {k: v.value for k, v in d.parts.items()} == e["parts"]
    assert d.fiyat > 10_000 and len(d.aciklama) > 20 and d.kimden in ("Sahibinden", "Galeriden", "Yetkili Bayiden")


def test_real_known_page_values():
    d = detail_parser.parse((REAL / "detail_1343930424.html").read_text(encoding="utf-8"))
    assert (d.marka, d.seri, d.yil, d.km, d.fiyat, str(d.ilan_tarihi)) == ("Fiat", "Albea", 2004, 238500, 215000, "2026-10-04")


@pytest.mark.parametrize("name", ["search_audi.html", "search_fiat.html", "search_renault.html"])
def test_real_search_pages(name):
    rows, nxt = list_parser.parse((REAL / name).read_text(encoding="utf-8"))
    assert len(rows) >= 15
    for r in rows:
        assert r.ilan_no.isdigit() and r.fiyat > 10_000 and 1950 < r.yil < 2100 and r.km >= 0
        assert r.marka and r.model and r.il != "Bilinmiyor" and r.url.startswith("/ilan/")
    assert nxt and "pagingOffset=20" in nxt


def test_unreadable_date_is_an_error_not_today():
    with pytest.raises(ValueError):
        list_parser.parse_date("dün")


def test_every_selector_reference_exists():
    """Seçici adı değişince çağıran kod çalışma anında kırılmasın (toplayıcı testlerde gerçek tarayıcı açmaz)."""
    import re as _re

    from arac_eksper.parser.selectors import Selectors
    root = pathlib.Path(__file__).resolve().parent.parent / "arac_eksper"
    refs = {m for f in root.rglob("*.py") for m in _re.findall(r"Selectors\.([A-Z_]+)", f.read_text(encoding="utf-8"))}
    assert refs and all(hasattr(Selectors, r) for r in refs), sorted(r for r in refs if not hasattr(Selectors, r))


def test_real_page_with_marker_word_is_not_a_block():
    from arac_eksper.collector.playwright_collector import detect_block
    from arac_eksper.parser.selectors import Selectors
    html = (REAL / "detail_1343930424.html").read_text(encoding="utf-8") + "<!-- captcha -->"
    assert detect_block(200, html, Selectors.DETAIL_INFO_LIST) is False
    assert detect_block(200, "<html>captcha</html>", Selectors.DETAIL_INFO_LIST) is True
