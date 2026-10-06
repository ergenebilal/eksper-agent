"""Fixture temizleyici: kişisel veri fixture'a girmez, ilan verisi (fiyat/km/ilan no) bozulmaz."""
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.fixture_sanitizer import sanitize

runner = CliRunner()

PAGE = """<html><head><meta name="csrf-token" content="abc123secret">
<script>window.user = {"name": "Ahmet Yılmaz", "phone": "0532 111 22 33"};</script></head><body>
<!-- oturum: ahmet@example.com -->
<div class="header-user-menu">Ahmet Yılmaz</div>
<form><input type="hidden" name="sess" value="tok"><input name="q" value="megane ankara"></form>
<span class="ilan-no">1234567890</span><span class="fiyat">845.000 TL</span><span class="km">98.000</span>
<div class="aciklama">Arayın 0532 111 22 33 veya ahmet@example.com. Plaka 34 ABC 123. Tramer 18.000 TL, 2018 model.</div>
<div class="classifiedUserBox"><h5>Ahmet Y.</h5><a href="tel:05321112233">Ara</a></div>
<img data-owner="ahmet@example.com" src="x.jpg">
</body></html>"""


def test_personal_data_removed_and_listing_data_kept():
    html, rep = sanitize(PAGE)
    for leak in ("0532 111 22 33", "05321112233", "ahmet@example.com", "34 ABC 123", "abc123secret",
                 "window.user", "megane ankara", 'value="tok"'):
        assert leak not in html, leak
    for keep in ("1234567890", "845.000 TL", "98.000", "Tramer 18.000 TL", "2018 model"):
        assert keep in html, keep
    assert rep["maskelenen"]["telefon"] >= 1 and rep["maskelenen"]["eposta"] >= 2 and rep["maskelenen"]["plaka"] == 1


def test_name_blocks_are_reported_without_their_text_and_removable():
    html, rep = sanitize(PAGE)
    secs = [b["secici"] for b in rep["supheli_bloklar"]]
    assert "div.header-user-menu" in secs and "div.classifiedUserBox" in secs
    assert "Ahmet" not in str(rep)                     # rapor kişisel metni basmaz
    html, rep = sanitize(PAGE, remove=[".classifiedUserBox", ".header-user-menu"])
    assert "Ahmet" not in html and rep["silinen_secici"][".classifiedUserBox"] == 1


def test_cli_writes_to_out_dir_and_never_overwrites_source(tmp_path):
    src = tmp_path / "ilan.html"
    src.write_text(PAGE, encoding="utf-8")
    out = tmp_path / "real"
    r = runner.invoke(cli.app, ["fixture", "sanitize", str(src), "--out", str(out), "--remove", ".classifiedUserBox"])
    assert r.exit_code == 0, r.output
    assert src.read_text(encoding="utf-8") == PAGE
    assert "0532 111 22 33" not in (out / "ilan.html").read_text(encoding="utf-8")
    assert "şüpheli blok" in r.output and "Ahmet" not in r.output
    assert runner.invoke(cli.app, ["fixture", "sanitize", str(src), "--out", str(tmp_path)]).exit_code == 3


def test_tyre_size_is_not_mistaken_for_a_plate():
    html, rep = sanitize("<table><tr><td>Lastik Ölçüleri</td><td class='value'>205/55 R16</td></tr></table><p>Plaka 34 ABC 123</p>")
    assert "205/55 R16" in html and "[plaka]" in html and rep["maskelenen"]["plaka"] == 1


def test_map_coordinates_are_removed():
    html, rep = sanitize('<div class="map" data-lat="40.1885" data-lon="29.0610" data-zoom="14">Harita</div>'
                         '<meta itemprop="latitude" data-latitude="40.1">')
    assert "40.1885" not in html and "29.0610" not in html and "40.1" not in html
    assert 'data-zoom="14"' in html and rep["silinen_konum"] == 3


def test_non_personal_hidden_flag_is_kept_with_value():
    html, _ = sanitize('<input id="priceHistoryFlag" type="hidden" value="true"><input type="hidden" name="s" value="tok">')
    assert 'id="priceHistoryFlag"' in html and 'value="true"' in html and "tok" not in html
