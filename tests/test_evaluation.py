"""Değerlendirme altyapısı: veri seti geçerliliği, metrik hesabı ve `arac eval` sözleşmesi (gerçek LLM çağrısı YOK)."""
import json
import re

import pytest
from typer.testing import CliRunner

from arac_eksper import cli
from arac_eksper.analysis import evaluation
from arac_eksper.analysis.description_llm import _amounts, _strip_tags, load_jargon
from arac_eksper.llm import client as llm_client
from arac_eksper.llm.client import LLMUnavailable
from arac_eksper.schemas import DescriptionFindings, Evidence

runner = CliRunner()
CASES = evaluation.load_dataset()


class OracleLLM:
    """Veri setindeki etiketleri birebir bilen sahte model: her iddiayı açıklamadan gerçek alıntıyla kurar."""
    def __init__(self, cases, drop: set[str] = frozenset()):
        self.by_text = {_strip_tags(c.aciklama): c for c in cases}
        self.drop = drop      # bu bayrakları "kaçır" (recall düşüşünü sınamak için)

    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        case = next(c for t, c in self.by_text.items() if t in user_prompt)
        fl = set(case.beklenen.bayraklar) - self.drop
        q = case.aciklama.split(",")[0].split(".")[0]          # açıklamada birebir geçen alıntı
        ev = [Evidence(etiket="x", alinti=q)]
        return DescriptionFindings(
            sase_direk_podye_islem="var" if "sase" in fl else "belirsiz", sase_alinti=q,
            airbag="acmis" if "airbag" in fl else "belirsiz", airbag_alinti=q,
            motor_sanziman="sorunlu" if "motor" in fl else "belirsiz", motor_alinti=q,
            agir_hasar_beyan="var" if "agir_hasar" in fl else "belirsiz", agir_hasar_alinti=q,
            km_degisimi_suphesi="km_suphesi" in fl,
            dolandiricilik_sinyalleri=ev if "dolandiricilik" in fl else [],
            belirsiz_ifadeler=ev if case.beklenen.olumsuz_var else [],
            tramer_tutari=case.beklenen.tramer_tutari,
        )


def test_dataset_is_valid_and_covers_every_flag():
    assert len(CASES) >= 30                                   # SPEC §4.1: en az 30 etiketli açıklama
    covered = {fl for c in CASES for fl in c.beklenen.bayraklar}
    assert covered == set(evaluation.FLAGS)
    assert sum(1 for c in CASES if not c.beklenen.bayraklar) >= 8   # yanlış alarmı ölçecek temiz vakalar


def test_expected_tramer_amounts_appear_in_text():
    for c in CASES:
        t = c.beklenen.tramer_tutari
        if t:
            assert t in _amounts(c.aciklama), c.id


def test_no_personal_data_in_dataset():
    for c in CASES:
        assert not re.search(r"\b0?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b", c.aciklama), c.id


def test_bad_dataset_line_names_the_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"id": "a", "kaynak": "sentetik", "aciklama": "x", "beklenen": {"bayraklar": ["uydurma"]}}\n',
                 encoding="utf-8")
    with pytest.raises(ValueError, match=r"x.jsonl:1"):
        evaluation.load_dataset(p)


def test_duplicate_ids_rejected(tmp_path):
    line = '{"id": "a", "kaynak": "sentetik", "aciklama": "x", "beklenen": {}}\n'
    p = tmp_path / "x.jsonl"
    p.write_text(line * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="tekrarlanan"):
        evaluation.load_dataset(p)


def test_oracle_scores_perfectly():
    rep = evaluation.evaluate(OracleLLM(CASES), CASES)
    assert rep.recall == 1.0 and rep.precision == 1.0
    assert rep.temiz_yanlis_alarm_orani == 0.0 and rep.tramer_dogruluk == 1.0 and rep.olumsuz_recall == 1.0
    assert rep.temiz_engel_orani == 0.0
    assert rep.hatali == 0


def test_missed_flags_lower_recall_and_are_listed():
    rep = evaluation.evaluate(OracleLLM(CASES, drop={"sase"}), CASES)
    n_sase = sum("sase" in c.beklenen.bayraklar for c in CASES)
    assert rep.bayrak_bazinda["sase"] == {"tp": 0, "fn": n_sase, "fp": 0}
    assert rep.recall < 1.0
    assert all(r.kacirilan == ["sase"] for r in rep.vakalar if "sase" in r.beklenen and len(r.beklenen) == 1)


def test_llm_failure_counts_as_missed_not_clean():
    class Down:
        def parse_structured(self, *a, **k):
            raise LLMUnavailable("havuz yok")
    rep = evaluation.evaluate(Down(), CASES)
    assert rep.hatali == len(CASES) and rep.recall == 0.0     # hata "temiz" sayılmaz


def test_eval_cli_json_and_exit_codes(monkeypatch):
    monkeypatch.setattr(llm_client, "OpenAIClient", lambda: OracleLLM(CASES))
    r = runner.invoke(cli.app, ["eval", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["gecti"] is True and data["n"] == len(CASES)

    monkeypatch.setattr(llm_client, "OpenAIClient", lambda: OracleLLM(CASES, drop={"sase", "motor"}))
    assert runner.invoke(cli.app, ["eval", "--json"]).exit_code == 1


def test_eval_cli_bad_input(tmp_path):
    assert runner.invoke(cli.app, ["eval", "--second-pass", "bazen"]).exit_code == 3
    assert runner.invoke(cli.app, ["eval", "--dataset", str(tmp_path / "yok.jsonl")]).exit_code == 3


def test_jargon_corrections_reach_the_prompt():
    j = load_jargon()
    assert "silindir kapağı" in j                    # kafa yapıldı ≠ ön bölüm hasarı
    assert "sıfır motor DEĞİLDİR" in j               # sandık motor ≠ sıfır motor
    assert "tavan hariç komple boyalı DEMEK DEĞİLDİR" in j
