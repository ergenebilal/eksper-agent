import pytest
from arac_eksper.privacy import mask_phones
from tests.helpers import detail_html
from arac_eksper.parser import detail_parser


@pytest.mark.parametrize("raw", ["0532 123 45 67", "05321234567", "+90 532 123 45 67", "(0532) 123-45-67",
                                 "0 532 123 45 67", "0224 555 11 22"])
def test_phone_formats_masked(raw):
    assert mask_phones(f"Arayın: {raw} lütfen") == "Arayın: [telefon] lütfen"


@pytest.mark.parametrize("keep", ["845.000 TL", "125.000 km", "1.250.000 TL", "2018 model", "Tramer 18.000 TL",
                                  "ilan no 1234567890123"])
def test_prices_and_km_untouched(keep):
    assert mask_phones(keep) == keep


def test_parser_masks_description():
    html = detail_html("123456", 800000, aciklama="Acil satılık 0532 123 45 67 arayın")
    d = detail_parser.parse(html, url="u")
    assert "0532" not in d.aciklama and "[telefon]" in d.aciklama
