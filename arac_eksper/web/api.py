"""otoXray AI uç noktaları (/api/v1). DURUMSUZ: ilan metni, başlık, bağlantı ya da karar sunucuda SAKLANMAZ.
Veritabanı, dosya, önbellek, günlük kaydı yoktur; her istek bellekte işlenir ve yanıt dönünce kapsam biter.
Piyasa emsalleri kullanıcının kendi tarayıcısında tutulur, istekle birlikte geçici gelir.
Yetki: yalnızca Bearer EXTENSION_TOKEN (çerez yok, CORS yok). İstemci verisi güvensizdir: sınırlar, beyaz listeler,
telefon maskeleme. Karar mantığı değişmedi: description_llm + rules_engine + offer."""
import re
import threading
import time
from collections import deque
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from arac_eksper.analysis import description_llm, market_calc, offer as offer_calc, rules_engine
from arac_eksper.config.rules_loader import load_rules
from arac_eksper.config.settings import settings
from arac_eksper.llm.client import LLMUnavailable, OpenAIClient
from arac_eksper.privacy import mask_phones
from arac_eksper.report.legal import DISCLAIMER
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import ListingDetail, MarketStats, PartState
from arac_eksper.web import security

router = APIRouter(prefix="/api/v1", dependencies=[Depends(security.require_extension_auth)])

ID_RE = r"^[A-Za-z0-9_-]{1,20}$"
PART_KEY = re.compile(r"^[a-z0-9_]{1,40}$")
NOT = "🟢 = “ekspertize götürmeye değer”, “al” değil. Şase, direk, podye ve airbag ilandan doğrulanamaz."

_calls: deque[float] = deque()          # yalnızca zaman damgaları (içerik YOK); yeniden başlatınca sıfırlanır
_calls_lock = threading.Lock()


def get_llm():
    return OpenAIClient()


# ------------------------------------------------------------------ istek şemaları
class Comp(BaseModel):
    """Kullanıcının tarayıcısında biriken emsal: yalnız sayısal teknik nitelikler."""
    id: str = Field(pattern=ID_RE)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)
    fiyat: int = Field(ge=1, le=500_000_000)
    seri: str | None = Field(None, max_length=60)


class AnalyzeRequest(BaseModel):
    ilan_no: str = Field(pattern=ID_RE)
    baslik: str = Field("", max_length=200)
    fiyat: int = Field(ge=1, le=500_000_000)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)
    marka: str | None = Field(None, max_length=60)
    model: str | None = Field(None, max_length=80)
    seri: str | None = Field(None, max_length=80)
    paket: str | None = Field(None, max_length=80)
    vites: str | None = Field(None, max_length=40)
    yakit: str | None = Field(None, max_length=40)
    kasa_tipi: str | None = Field(None, max_length=40)
    motor_hacmi: str | None = Field(None, max_length=40)
    renk: str | None = Field(None, max_length=40)
    agir_hasar_kayitli: bool | None = None
    tramer_tutari_yapilandirilmis: int | None = Field(None, ge=0, le=500_000_000)
    parts: dict[str, PartState] = Field(default_factory=dict)
    aciklama: str = Field("", max_length=8000)
    max_butce: int | None = Field(None, ge=1, le=500_000_000)
    emsal: list[Comp] = Field(default_factory=list, max_length=300)

    @field_validator("parts")
    @classmethod
    def _parts(cls, v):
        if len(v) > 40 or any(not PART_KEY.match(k) for k in v):
            raise ValueError("parça adları geçersiz")
        return v


class BatchItem(BaseModel):
    ilan_no: str = Field(pattern=ID_RE)
    seri: str | None = Field(None, max_length=60)
    fiyat: int = Field(ge=1, le=500_000_000)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=80)
    emsal: list[Comp] = Field(default_factory=list, max_length=300)


# ------------------------------------------------------------------ yardımcılar
def _comps(emsal: list[Comp]) -> list[market_calc.Comparable]:
    return [(c.id, c.yil, c.km, c.fiyat, c.seri) for c in emsal]


def _llm_budget_ok() -> bool:
    """Günlük LLM çağrı sınırı: yalnız sayaç (zaman damgaları) tutulur, içerik tutulmaz."""
    now = time.time()
    with _calls_lock:
        while _calls and now - _calls[0] > 86400:
            _calls.popleft()
        if len(_calls) >= settings.analyze_daily_limit:
            return False
        _calls.append(now)
        return True


def _kanitlar(findings) -> tuple[list[dict], list[dict]]:
    """(kanıt listesi, vurgu listesi): yalnız sunucunun açıklamada DOĞRULADIĞI alıntılar."""
    if not findings:
        return [], []
    out = []
    for tur, lst in (("olumlu", findings.olumlu_sinyaller), ("olumsuz", findings.olumsuz_sinyaller),
                     ("dolandiricilik", findings.dolandiricilik_sinyalleri), ("belirsiz", findings.belirsiz_ifadeler)):
        out += [{"tur": tur, "etiket": e.etiket, "alinti": e.alinti} for e in lst]
    for etiket, claim_ok, alinti in (
        ("Şase/podye/direk işlemi", findings.sase_direk_podye_islem == "var", findings.sase_alinti),
        ("Airbag açmış", findings.airbag == "acmis", findings.airbag_alinti),
        ("Motor/şanzıman sorunu", findings.motor_sanziman in ("degisen", "sorunlu"), findings.motor_alinti),
        ("Pert/çekme belgeli/ağır hasar", findings.agir_hasar_beyan == "var", findings.agir_hasar_alinti)):
        if claim_ok and alinti:
            out.append({"tur": "olumsuz", "etiket": etiket, "alinti": alinti})
    vurgu_tur = {"olumlu": "olumlu", "olumsuz": "olumsuz", "dolandiricilik": "olumsuz", "belirsiz": "belirsiz"}
    return out, [{"alinti": k["alinti"], "tur": vurgu_tur[k["tur"]]} for k in out]


def _sapma(fiyat: int, medyan: int | None):
    return round((fiyat - medyan) / medyan * 100, 1) if medyan and medyan > 0 else None


def _detail(req: AnalyzeRequest) -> ListingDetail:
    return ListingDetail(
        ilan_no=req.ilan_no, url="", baslik=mask_phones(req.baslik), fiyat=req.fiyat, yil=req.yil, km=req.km,
        il="Bilinmiyor", ilan_tarihi=date.today(), marka=req.marka or "", model=req.model or "", seri=req.seri,
        paket=req.paket, vites=req.vites, yakit=req.yakit, kasa_tipi=req.kasa_tipi, motor_hacmi=req.motor_hacmi,
        renk=req.renk, agir_hasar_kayitli=req.agir_hasar_kayitli,
        tramer_tutari_yapilandirilmis=req.tramer_tutari_yapilandirilmis, parts=req.parts,
        aciklama=mask_phones(req.aciklama), fetched_at=datetime.now(timezone.utc))


def _pending(req: AnalyzeRequest) -> dict:
    return {"ilan_no": req.ilan_no, "beklemede": True, "etiket": None, "skor": 0.0, "veri_tamlik": 0.0,
            "hard_fails": [], "artilar": [], "eksiler": ["LLM analizi bekliyor (havuza erişilemedi)"], "trace": [],
            "piyasa": None, "sapma_yuzde": None, "tavsiye_teklif": None, "ust_sinir": None,
            "ekspertiz_kontrol_listesi": [], "kanitlar": [], "vurgu": [], "whatsapp_metni": None,
            "uyari": NOT, "yasal_uyari": DISCLAIMER}


# ------------------------------------------------------------------ uç noktalar
@router.get("/ping")
def ping():
    return {"ok": True, "surum": 2, "durumsuz": True, "yasal_uyari": DISCLAIMER}


@router.post("/analyze")
def analyze(req: AnalyzeRequest, llm=Depends(get_llm)):
    if not _llm_budget_ok():
        raise HTTPException(status_code=429, detail="Günlük analiz sınırı doldu")
    detail = _detail(req)
    stats = market_calc.stats_from_comparables(req.ilan_no, req.yil, req.km, _comps(req.emsal), req.seri)
    try:
        findings = description_llm.analyze_description(llm, detail.baslik, detail.aciklama)   # db yok → önbellek yok
    except (LLMUnavailable, ValueError):       # pydantic.ValidationError bir ValueError'dır
        return _pending(req)
    v = rules_engine.determine_verdict(detail, findings, stats, max_butce=req.max_butce)
    # Açıklamalı teklif: piyasa varsa piyasadan, yoksa YALNIZ ilan fiyatından (kaynak="ilan", düşük güven)
    b = offer_calc.breakdown(detail, findings, v, allow_no_market=True)
    if b:
        v.tavsiye_teklif, v.ust_sinir = b["acilis"], b["ust_sinir"]
    kanitlar, vurgu = _kanitlar(findings)
    return {
        "ilan_no": req.ilan_no, "beklemede": False, "etiket": v.etiket, "skor": v.guven_skoru,
        "veri_tamlik": v.veri_tamlik, "hard_fails": v.hard_fails, "artilar": v.artilar, "eksiler": v.eksiler,
        "trace": v.trace,
        "piyasa": {"n": stats.n, "medyan": stats.medyan, "p25": stats.p25, "p75": stats.p75, "guven": stats.guven,
                   "min_emsal": load_rules()["etiket"]["min_emsal"]},
        "teklif": b,
        "sapma_yuzde": _sapma(req.fiyat, stats.medyan), "tavsiye_teklif": v.tavsiye_teklif, "ust_sinir": v.ust_sinir,
        "ekspertiz_kontrol_listesi": v.ekspertiz_kontrol_listesi, "kanitlar": kanitlar, "vurgu": vurgu,
        "whatsapp_metni": whatsapp_text(detail, v), "uyari": NOT, "yasal_uyari": DISCLAIMER,
    }


def rozet(sapma: float | None, n: int, rules: dict) -> tuple[str, str]:
    """Liste rozeti: YALNIZ fiyata dair, nötr dil. Karar etiketi değildir."""
    et, bt = rules["etiket"], rules["bantlar"]
    if sapma is None or n < et["min_emsal"]:
        return "emsal_yetersiz", f"Benzer ilan az ({n}/{et['min_emsal']})"
    s = sapma / 100
    if s < bt["sapma_ucuz_uyari"]:
        return "cok_ucuz_suphe", f"⚠ %{abs(sapma):.0f} ucuz: önce nedenini sor"
    if s <= et["alinir_max_sapma"]:
        return "avantajli", f"Fiyat avantajlı (-%{abs(sapma):.0f})"
    if s > rules["rozet"]["pahali_esik"]:
        return "pahali", f"Pahalı (+%{sapma:.0f})"
    return "piyasada", "Piyasa değerinde"


@router.post("/batch-evaluate")
def batch_evaluate(req: BatchRequest):
    rules = load_rules()
    comps = _comps(req.emsal)
    now_year = datetime.now(timezone.utc).year
    sonuc = []
    for it in req.items:
        st: MarketStats = market_calc.stats_from_comparables(it.ilan_no, it.yil, it.km, comps, it.seri)
        sapma = _sapma(it.fiyat, st.medyan or None)
        kod, metin = rozet(sapma, st.n, rules)
        yillik = round(it.km / max(now_year - it.yil, 1))
        sonuc.append({"ilan_no": it.ilan_no, "rozet": kod, "rozet_metin": metin, "sapma_yuzde": sapma,
                      "emsal_n": st.n, "emsal_medyan": st.medyan or None, "yillik_km": yillik,
                      "km_uyari": yillik > rules["hard_fails"]["max_yillik_km"]})
    return {"sonuclar": sonuc, "uyari": "Rozetler yalnız fiyata dairdir; karar değildir.", "yasal_uyari": DISCLAIMER}
