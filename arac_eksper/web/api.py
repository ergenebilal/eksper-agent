"""otoXray AI uç noktaları (/api/v1). İLAN VERİSİ AÇISINDAN DURUMSUZ: ilan metni, başlık, bağlantı ya da karar sunucuda
SAKLANMAZ; ilan önbelleği ve günlük kaydı yoktur, her istek bellekte işlenir. Tek kalıcı kayıt davetli kullanıcı hesabıdır
(web/accounts.py: anahtar özeti, günlük sayaç, kullanıcının bilerek gönderdiği geri bildirim); sahip anahtarı ona da dokunmaz.
Piyasa emsalleri kullanıcının kendi tarayıcısında tutulur, istekle birlikte geçici gelir.
Yetki: yalnızca Bearer EXTENSION_TOKEN (çerez yok, CORS yok). İstemci verisi güvensizdir: sınırlar, beyaz listeler,
telefon maskeleme. Karar mantığı değişmedi: description_llm + rules_engine + offer."""
import re
import threading
import time
from collections import deque
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from arac_eksper.analysis import description_llm, market_calc, offer as offer_calc, rules_engine
from arac_eksper.config.rules_loader import load_rules
from arac_eksper.config.settings import settings
from arac_eksper.llm.client import LLMUnavailable, OpenAIClient
from arac_eksper.privacy import mask_phones
from arac_eksper.report.legal import DISCLAIMER
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import DescriptionFindings, ListingDetail, MarketStats, PartState, Verdict
from arac_eksper.web import accounts, security

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


def current_user(request: Request) -> dict:
    return request.state.user


def _take(user: dict, tur: str, limit: int | None) -> None:
    """Davetli kullanıcının günlük hakkından düşer; sahip (id 0) hesap deposuna hiç dokunmaz."""
    if user["id"] and not accounts.consume(user["id"], limit, tur):
        raise HTTPException(status_code=429, detail=f"Günlük hakkınız doldu ({limit}). Yarın yenilenir.")


def _kota(user: dict) -> dict | None:
    if not user["id"]:
        return None
    return {"limit": user["gunluk_kota"], "kullanilan": accounts.used_today(user["id"])}


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
def ping(user=Depends(current_user)):
    return {"ok": True, "surum": 3, "durumsuz": True, "kullanici": user["ad"], "kota": _kota(user),
            "yasal_uyari": DISCLAIMER}


@router.post("/quick")
def quick(req: AnalyzeRequest, user=Depends(current_user)):
    """LLM'siz ANINDA ön hesap: piyasa, yapıdan elenme nedenleri ve ön teklif. LLM röntgeni beklenirken gösterilir;
    etiket ÜRETMEZ (açıklama analizi olmadan karar verilmez). LLM bütçesinden düşmez, hiçbir şey saklanmaz."""
    _take(user, "quick", settings.user_daily_batch)
    detail = _detail(req)
    stats = market_calc.stats_from_comparables(req.ilan_no, req.yil, req.km, _comps(req.emsal), req.seri)
    empty = DescriptionFindings(sase_direk_podye_islem="belirsiz", airbag="belirsiz", motor_sanziman="belirsiz",
                                km_degisimi_suphesi=False)
    rules = load_rules()
    hard = rules_engine.evaluate_hard_fails(detail, empty, stats, rules, req.max_butce)
    pending = Verdict(ilan_no=req.ilan_no, etiket="DUSUNULEBILIR", guven_skoru=0.0, veri_tamlik=0.0, piyasa=stats)
    b = None if hard else offer_calc.breakdown(detail, empty, pending, allow_no_market=True)
    return {"ilan_no": req.ilan_no, "on_hesap": True, "elenme_nedenleri": hard,
            "piyasa": {"n": stats.n, "medyan": stats.medyan, "p25": stats.p25, "p75": stats.p75, "guven": stats.guven,
                       "min_emsal": rules["etiket"]["min_emsal"]},
            "sapma_yuzde": _sapma(req.fiyat, stats.medyan), "teklif": b, "yasal_uyari": DISCLAIMER}


@router.post("/analyze")
def analyze(req: AnalyzeRequest, llm=Depends(get_llm), user=Depends(current_user)):
    _take(user, "analyze", user["gunluk_kota"])
    if not _llm_budget_ok():
        if user["id"]:
            accounts.refund(user["id"])
        raise HTTPException(status_code=429, detail="Sunucunun günlük analiz sınırı doldu")
    detail = _detail(req)
    stats = market_calc.stats_from_comparables(req.ilan_no, req.yil, req.km, _comps(req.emsal), req.seri)
    try:
        findings = description_llm.analyze_description(llm, detail.baslik, detail.aciklama,    # db yok → önbellek yok
                                                      second_pass=settings.xray_second_pass)
    except (LLMUnavailable, ValueError):       # pydantic.ValidationError bir ValueError'dır
        if user["id"]:
            accounts.refund(user["id"])         # analiz yapılamadıysa hak yanmaz
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
        "trace": v.trace if not user["id"] else [],     # kural ağırlıkları yalnız sahibe: davetliden kopyalanamasın
        "piyasa": {"n": stats.n, "medyan": stats.medyan, "p25": stats.p25, "p75": stats.p75, "guven": stats.guven,
                   "min_emsal": load_rules()["etiket"]["min_emsal"]},
        "teklif": b,
        "sapma_yuzde": _sapma(req.fiyat, stats.medyan), "tavsiye_teklif": v.tavsiye_teklif, "ust_sinir": v.ust_sinir,
        "ekspertiz_kontrol_listesi": v.ekspertiz_kontrol_listesi, "kanitlar": kanitlar, "vurgu": vurgu,
        "whatsapp_metni": whatsapp_text(detail, v), "uyari": NOT, "yasal_uyari": DISCLAIMER, "kota": _kota(user),
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
def batch_evaluate(req: BatchRequest, user=Depends(current_user)):
    _take(user, "batch", settings.user_daily_batch)
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


# ------------------------------------------------------------------ geri bildirim (davetli kullanım)
class FeedbackRequest(BaseModel):
    """Kullanıcının BİLEREK gönderdiği geri bildirim. Açıklama/başlık/fiyat alınmaz; not kısa ve telefonu maskelenir."""
    ilan_no: str = Field(pattern=ID_RE)
    etiket: Literal["ALINIR", "DUSUNULEBILIR", "ALINMAZ"] | None = None
    skor: float | None = Field(None, ge=0, le=10)
    oy: Literal["pos", "neg"] | None = None
    sonuc: Literal[accounts.SONUCLAR] | None = None
    notu: str | None = Field(None, max_length=500)


@router.post("/feedback")
def feedback(req: FeedbackRequest, user=Depends(current_user)):
    if not (req.oy or req.sonuc or (req.notu or "").strip()):
        raise HTTPException(status_code=422, detail="Oy, ekspertiz sonucu ya da not gerekli")
    if not user["id"]:
        return {"ok": True, "kaydedildi": False, "neden": "sahip anahtarı: geri bildirim saklanmaz"}
    _take(user, "feedback", settings.feedback_daily_limit)
    notu = mask_phones(req.notu.strip())[:500] if req.notu and req.notu.strip() else None
    fid = accounts.add_feedback(user["id"], req.ilan_no, req.etiket, req.skor, req.oy, req.sonuc, notu)
    return {"ok": True, "kaydedildi": True, "id": fid}
