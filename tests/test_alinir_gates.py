"""K1/K2: bilinmeyen veya riskli sinyal varken ilan 🟢 olamaz (kural 9: bilinmeyen 'iyi' sayılmaz)."""
from arac_eksper.analysis.rules_engine import determine_verdict, load_rules
from arac_eksper.schemas import PartState, Evidence
from tests.test_hard_fails import _detail, _findings, MKT

GOOD = dict(fiyat=820000)
ALINIR_OK = lambda: determine_verdict(_detail(**GOOD), _findings(), MKT, max_butce=900000)


def test_baseline_is_alinir():
    assert ALINIR_OK().etiket == "ALINIR"


def test_missing_diagram_is_penalized_and_blocks_alinir():
    v = determine_verdict(_detail(parts={}, **GOOD), _findings(), MKT, max_butce=900000)
    assert v.etiket == "DUSUNULEBILIR"
    assert any("diyagram" in t["kural"].lower() for t in v.trace)
    assert any("ALINIR engeli" in e for e in v.eksiler)
    assert v.veri_tamlik < ALINIR_OK().veri_tamlik


def test_all_unknown_parts_block_alinir_and_lower_completeness():
    parts = {"tavan": PartState.UNKNOWN, "kaput": PartState.UNKNOWN}
    v = determine_verdict(_detail(parts=parts, **GOOD), _findings(), MKT, max_butce=900000)
    assert v.etiket == "DUSUNULEBILIR"
    assert v.veri_tamlik < 1.0


def test_fraud_signal_blocks_alinir():
    f = _findings(dolandiricilik_sinyalleri=[Evidence(etiket="kapora", alinti="kapora")])
    v = determine_verdict(_detail(**GOOD), f, MKT, max_butce=900000)
    assert v.etiket == "DUSUNULEBILIR" and not v.hard_fails


def test_engine_problem_blocks_alinir():
    for state in ("sorunlu", "degisen"):
        v = determine_verdict(_detail(**GOOD), _findings(motor_sanziman=state), MKT, max_butce=900000)
        assert v.etiket == "DUSUNULEBILIR", state


def test_km_tampering_suspicion_blocks_alinir():
    v = determine_verdict(_detail(**GOOD), _findings(km_degisimi_suphesi=True), MKT, max_butce=900000)
    assert v.etiket == "DUSUNULEBILIR"


def test_gates_never_turn_red_into_green_or_yellow_into_red():
    # kapılar yalnızca ALINIR'ı yumuşatır; hard fail yine ALINMAZ
    f = _findings(motor_sanziman="sorunlu", sase_direk_podye_islem="var")
    assert determine_verdict(_detail(**GOOD), f, MKT, max_butce=900000).etiket == "ALINMAZ"
