import pytest
import os
from arac_eksper.parser import list_parser, detail_parser

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_list_parser():
    with open(os.path.join(FIXTURES_DIR, "list_1.html"), "r", encoding="utf-8") as f:
        html = f.read()
        
    listings, next_page = list_parser.parse(html)
    
    assert len(listings) == 2
    assert listings[0].ilan_no == "123456789"
    assert listings[0].fiyat == 850000
    assert listings[0].km == 95000
    assert next_page == "/arama?page=2"

def test_detail_parser():
    with open(os.path.join(FIXTURES_DIR, "detail_1.html"), "r", encoding="utf-8") as f:
        html = f.read()
        
    detail = detail_parser.parse(html, url="http://test")
    
    assert detail.ilan_no == "123456789"
    assert detail.fiyat == 850000
    assert detail.yil == 2018
    assert detail.km == 95000
    assert detail.vites == "Otomatik"
    assert detail.agir_hasar_kayitli is False
    assert "Aracım temizdir" in detail.aciklama
    
    assert "motor_kaputu" in detail.parts
    assert detail.parts["motor_kaputu"] == "degisen"
    assert detail.parts["tavan"] == "orijinal"
