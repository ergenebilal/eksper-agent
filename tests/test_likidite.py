"""R4.3 likidite v0: bant + gerekçe, gün sayısı yok, onaysız kural etkisiz, emsal/ilan yaşı yalnız not."""
from datetime import date, timedelta

from arac_eksper.analysis import likidite as lq

BUGUN = date(2026, 10, 7)


def kural(**kw):
    return dict({"kod": "x", "kosul": {}, "bant": "hizli", "gerekce": "g", "onayli": True}, **kw)


def test_first_matching_rule_wins_and_conditions_combine():
    k = [kural(kod="lpg", kosul={"yakit": ["lpg"]}, bant="orta"),
         kural(kod="buyuk", kosul={"yakit": ["benzin"], "motor_cc_min": 2000}, bant="yavas"),
         kural(kod="eko", kosul={"segment": ["ekonomik"], "yakit": ["dizel"]}, bant="hizli")]
    d = {"marka": "Fiat", "seri": "Egea", "yakit": "Dizel", "vites": "Manuel", "motor_hacmi": "1301 - 1600 cm3", "yil": 2019}
    assert lq.likidite(d, kural_listesi=k, bugun=BUGUN)["bant"] == "hizli"
    assert lq.likidite(dict(d, yakit="Benzin & LPG"), kural_listesi=k)["bant"] == "orta"
    assert lq.likidite(dict(d, yakit="Benzin", motor_hacmi="2001 - 2500 cm3"), kural_listesi=k)["bant"] == "yavas"
    assert lq.likidite(dict(d, yakit="Benzin", motor_hacmi="1801 - 2000 cm3"), kural_listesi=k)["bant"] is None


def test_unapproved_rules_have_no_effect_but_are_reported():
    r = lq.likidite({"marka": "Fiat", "seri": "Egea", "yakit": "Dizel", "vites": "Manuel", "yil": 2019})
    assert r["bant"] is None and r["onay_bekliyor"] is True       # taslak KB: tüm kurallar onaysız


def test_user_data_only_adds_notes_never_days_estimate():
    r = lq.likidite({"yakit": "Dizel"}, emsal_n=42, ilan_tarihi=BUGUN - timedelta(days=50), bugun=BUGUN, kural_listesi=[])
    assert r["bant"] is None and any("42 ilan" in n for n in r["notlar"])
    assert "tahmini değildir" in r["uyari"]


def test_kb_file_is_valid_and_all_draft():
    errs, warns = lq.validate()
    assert errs == [] and warns
    assert lq.kurallar() == []                     # kullanıcı onayına kadar
