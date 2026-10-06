"""Açıklama röntgeninin etiketli veri setiyle ölçülmesi (SPEC §4.1 kabul: kırmızı bayrak recall ≥ %90).

Veri seti JSONL'dir, her satır bir ilan açıklaması ve beklenen bayraklardır (bkz. tests/data/README.md).
Ölçüm üretim yolunu birebir kullanır (analyze_description: kanıt doğrulama + ikinci geçiş) ama önbellek/DB kullanmaz.
"""
import json
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from arac_eksper.analysis.description_llm import analyze_description
from arac_eksper.llm.client import LLMClient, LLMUnavailable
from arac_eksper.schemas import DescriptionFindings

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "tests" / "data" / "aciklamalar.jsonl"

Flag = Literal["sase", "airbag", "motor", "agir_hasar", "dolandiricilik", "km_suphesi"]
FLAGS: tuple[str, ...] = Flag.__args__


class Expected(BaseModel):
    bayraklar: list[Flag] = Field(default_factory=list)   # kırmızı bayraklar: tam küme beklenir
    tramer_tutari: int | None = None                       # açıklamada yazan tutar; 0 = 'tramer yok' beyanı; None = söz yok
    olumsuz_var: bool = False                              # en az bir olumsuz/belirsiz sinyal beklenir


class Case(BaseModel):
    id: str
    kaynak: Literal["sentetik", "gercek"]
    baslik: str = ""
    aciklama: str
    beklenen: Expected
    not_: str | None = Field(None, alias="not")


def load_dataset(path: Path = DEFAULT_DATASET) -> list[Case]:
    cases, ids = [], set()
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = Case.model_validate_json(line)
        except ValueError as e:
            raise ValueError(f"{path}:{i}: geçersiz satır: {e}") from None
        if case.id in ids:
            raise ValueError(f"{path}:{i}: tekrarlanan id {case.id}")
        ids.add(case.id)
        cases.append(case)
    return cases


def flags_of(f: DescriptionFindings) -> set[str]:
    out = set()
    if f.sase_direk_podye_islem == "var":
        out.add("sase")
    if f.airbag == "acmis":
        out.add("airbag")
    if f.motor_sanziman in ("degisen", "sorunlu"):
        out.add("motor")
    if f.agir_hasar_beyan == "var":
        out.add("agir_hasar")
    if f.dolandiricilik_sinyalleri:
        out.add("dolandiricilik")
    if f.km_degisimi_suphesi:
        out.add("km_suphesi")
    return out


class CaseResult(BaseModel):
    id: str
    beklenen: list[str]
    bulunan: list[str]
    kacirilan: list[str]          # FN: güvenlik açısından en kritik hata
    yanlis_alarm: list[str]       # FP
    tramer_dogru: bool | None     # LLM hatasında None; 'söz yok' vakasında uydurma tutar da yanlıştır
    olumsuz_dogru: bool | None    # olumsuz_var beklenmiyorsa None
    dogrulanamayan_iddia: bool
    sure_sn: float
    hata: str | None = None


class Report(BaseModel):
    n: int
    hatali: int
    recall: float | None          # Σ TP / Σ (TP+FN); bayrak beklenen yoksa None
    precision: float | None
    temiz_yanlis_alarm_orani: float | None   # bayraksız vakalardan bayrak alanların oranı
    tramer_dogruluk: float | None
    olumsuz_recall: float | None
    bayrak_bazinda: dict[str, dict[str, int]]
    ort_sure_sn: float
    vakalar: list[CaseResult]


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def run_case(client: LLMClient, case: Case, second_pass: str) -> CaseResult:
    t0 = time.perf_counter()
    exp = set(case.beklenen.bayraklar)
    try:
        f = analyze_description(client, case.baslik, case.aciklama, second_pass=second_pass)
    except LLMUnavailable as e:
        return CaseResult(id=case.id, beklenen=sorted(exp), bulunan=[], kacirilan=sorted(exp), yanlis_alarm=[],
                          tramer_dogru=None, olumsuz_dogru=None, dogrulanamayan_iddia=False,
                          sure_sn=round(time.perf_counter() - t0, 2), hata=str(e))
    got = flags_of(f)
    tramer_ok = f.tramer_tutari == case.beklenen.tramer_tutari
    olumsuz_ok = (bool(f.olumsuz_sinyaller or f.belirsiz_ifadeler)) if case.beklenen.olumsuz_var else None
    return CaseResult(id=case.id, beklenen=sorted(exp), bulunan=sorted(got), kacirilan=sorted(exp - got),
                      yanlis_alarm=sorted(got - exp), tramer_dogru=tramer_ok, olumsuz_dogru=olumsuz_ok,
                      dogrulanamayan_iddia=f.dogrulanamayan_iddia, sure_sn=round(time.perf_counter() - t0, 2))


def summarize(results: list[CaseResult]) -> Report:
    ok = [r for r in results if r.hata is None]
    per = {fl: Counter() for fl in FLAGS}
    for r in ok:
        for fl in r.beklenen:
            per[fl]["tp" if fl in r.bulunan else "fn"] += 1
        for fl in r.yanlis_alarm:
            per[fl]["fp"] += 1
    tp = sum(c["tp"] for c in per.values())
    fn = sum(c["fn"] for c in per.values())
    fp = sum(c["fp"] for c in per.values())
    # LLM hatası "temiz" sayılmaz: hatalı vakanın beklenen bayrakları kaçırılmış (FN) olarak recall'a girer
    fn += sum(len(r.beklenen) for r in results if r.hata is not None)
    clean = [r for r in ok if not r.beklenen]
    tramer = [r.tramer_dogru for r in ok if r.tramer_dogru is not None]
    olumsuz = [r.olumsuz_dogru for r in ok if r.olumsuz_dogru is not None]
    return Report(
        n=len(results), hatali=len(results) - len(ok),
        recall=_ratio(tp, tp + fn), precision=_ratio(tp, tp + fp),
        temiz_yanlis_alarm_orani=_ratio(sum(1 for r in clean if r.bulunan), len(clean)),
        tramer_dogruluk=_ratio(sum(tramer), len(tramer)),
        olumsuz_recall=_ratio(sum(olumsuz), len(olumsuz)),
        bayrak_bazinda={fl: {k: c[k] for k in ("tp", "fn", "fp")} for fl, c in per.items()},
        ort_sure_sn=round(sum(r.sure_sn for r in results) / len(results), 2) if results else 0.0,
        vakalar=results,
    )


def evaluate(client: LLMClient, cases: list[Case], second_pass: str = "hard", on_case=None) -> Report:
    """on_case(i, n, CaseResult): her vaka bitince çağrılır (ilerleme göstermek için)."""
    results = []
    for i, c in enumerate(cases, 1):
        results.append(run_case(client, c, second_pass))
        if on_case:
            on_case(i, len(cases), results[-1])
    return summarize(results)
