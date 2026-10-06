"""R2.1 masraf bilgi tabanı: şema, onay kuralı (kural 10), segment eşleşmesi, aralık, eskime uyarısı."""
from datetime import date

import yaml

from arac_eksper.analysis import masraf_kb


def test_file_is_valid_and_every_item_is_a_range_in_all_segments():
    errs, warns = masraf_kb.validate(today=date(2026, 10, 7))
    assert errs == [] and warns == []
    tum = masraf_kb.kalemler(include_unapproved=True)
    assert len(tum) >= 40
    for k in tum.values():
        assert all(0 < k["aralik"][s][0] <= k["aralik"][s][1] for s in masraf_kb.SEGMENTLER), k["kod"]
        assert k["anahtar_kelimeler"]


def test_unapproved_items_are_not_usable(tmp_path):
    d = yaml.safe_load(masraf_kb.KB_PATH.read_text(encoding="utf-8"))
    for k in d["kalemler"]:
        k["onayli"] = False
    d["kalemler"][0]["onayli"] = True
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    onayli = masraf_kb.kalemler(path=p)
    assert list(onayli) == [d["kalemler"][0]["kod"]]
    assert masraf_kb.aralik(d["kalemler"][1]["kod"], "orta", onayli) is None       # onaysız → tutar yok


def test_segments_for_real_listing_models():
    kb = masraf_kb.load()
    cases = {("Renault", "Megane"): "orta", ("Renault", "Clio"): "ekonomik", ("Fiat", "Albea"): "ekonomik",
             ("Tofaş", "Doğan"): "ekonomik", ("Toyota", "Corolla"): "orta", ("Volkswagen", "Passat"): "ust",
             ("Citroen", "C5"): "ust", ("Audi", "A6"): "premium", ("BMW", "3 Serisi"): "premium",
             ("Peugeot", "301"): "ekonomik", ("Lada", "Niva"): "bilinmiyor"}
    for (marka, seri), seg in cases.items():
        assert masraf_kb.segment(marka, seri, kb) == seg, (marka, seri)
    assert masraf_kb.segment("TOFAS", "dogan", kb) == "ekonomik"              # harf katlama


def test_unknown_segment_gets_a_wide_cautious_range():
    km = {"x": {"kod": "x", "aralik": {"ekonomik": [10, 20], "orta": [15, 30], "ust": [25, 50], "premium": [40, 90]}}}
    assert masraf_kb.aralik("x", "orta", km) == (15, 30)
    assert masraf_kb.aralik("x", "bilinmiyor", km) == (10, 50)


def test_stale_prices_warn_and_bad_entries_error(tmp_path):
    d = yaml.safe_load(masraf_kb.KB_PATH.read_text(encoding="utf-8"))
    _, warns = masraf_kb.validate(today=date(2027, 6, 1))
    assert any("aydan eski" in w for w in warns)
    d["kalemler"][0]["aralik"]["orta"] = [500, 100]
    d["kalemler"][1]["kod"] = d["kalemler"][0]["kod"]
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    errs, _ = masraf_kb.validate(path=p, today=date(2026, 10, 7))
    assert any("aralik.orta" in e for e in errs) and any("tekrar" in e for e in errs)
