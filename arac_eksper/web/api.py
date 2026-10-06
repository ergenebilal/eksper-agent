"""Chrome eklentisi için /api/v1. Yetki: yalnızca Bearer EXTENSION_TOKEN (çerez yok, CORS yok).
İstemci verisi GÜVENSİZdir: ayrı istek şemaları, sınırlar, beyaz listeler, sunucu zaman damgası, telefon maskeleme.
Karar mantığı değişmedi: pipeline.evaluate_detail + rules_engine aynen kullanılır."""
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from arac_eksper import pipeline
from arac_eksper.analysis import description_llm, identify, market
from arac_eksper.config.rules_loader import load_rules
from arac_eksper.config.settings import settings
from arac_eksper.llm.client import OpenAIClient
from arac_eksper.privacy import mask_phones
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import ListingDetail, ListingSummary, PartState
from arac_eksper.storage import repo
from arac_eksper.storage.models import LLMCache
from arac_eksper.web import security, service
from arac_eksper.web.app_deps import get_db

router = APIRouter(prefix="/api/v1", dependencies=[Depends(security.require_extension_auth)])

ID_RE = r"^[A-Za-z0-9_-]{1,20}$"
PART_KEY = re.compile(r"^[a-z0-9_]{1,40}$")
UYARI = "🟢 = “ekspertize götürmeye değer”, “al” değil. Şase, direk, podye ve airbag ilandan doğrulanamaz."


def get_llm():
    return OpenAIClient()


# ------------------------------------------------------------------ istek şemaları
class AnalyzeRequest(BaseModel):
    ilan_no: str = Field(pattern=ID_RE)
    url: str | None = Field(None, max_length=300)
    baslik: str = Field(max_length=200)
    fiyat: int = Field(ge=1, le=500_000_000)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)
    il: str | None = Field(None, max_length=60)
    ilce: str | None = Field(None, max_length=60)
    marka: str | None = Field(None, max_length=60)
    model: str | None = Field(None, max_length=80)
    seri: str | None = Field(None, max_length=80)
    paket: str | None = Field(None, max_length=80)
    vites: str | None = Field(None, max_length=40)
    yakit: str | None = Field(None, max_length=40)
    kasa_tipi: str | None = Field(None, max_length=40)
    motor_hacmi: str | None = Field(None, max_length=40)
    renk: str | None = Field(None, max_length=40)
    kimden: str | None = Field(None, max_length=40)
    agir_hasar_kayitli: bool | None = None
    tramer_tutari_yapilandirilmis: int | None = Field(None, ge=0, le=500_000_000)
    parts: dict[str, PartState] = Field(default_factory=dict)
    aciklama: str = Field("", max_length=8000)
    max_butce: int | None = Field(None, ge=1, le=500_000_000)
    page_path: str | None = Field(None, max_length=200)

    @field_validator("parts")
    @classmethod
    def _parts(cls, v):
        if len(v) > 40 or any(not PART_KEY.match(k) for k in v):
            raise ValueError("parça adları geçersiz")
        return v


class BatchItem(BaseModel):
    ilan_no: str = Field(pattern=ID_RE)
    baslik: str | None = Field(None, max_length=200)
    fiyat: int = Field(ge=1, le=500_000_000)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)
    il: str | None = Field(None, max_length=60)
    url: str | None = Field(None, max_length=300)
    marka: str | None = Field(None, max_length=60)
    model: str | None = Field(None, max_length=80)


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=80)
    page_path: str | None = Field(None, max_length=200)
    remember: bool = True      # sayfada görünen satırlar yerel piyasa DB'sine pasif eklensin


# ------------------------------------------------------------------ yardımcılar
def build_detail(req: AnalyzeRequest, db: Session) -> ListingDetail:
    marka, model = identify.resolve(req.marka, req.model, req.baslik, req.page_path, db)
    return ListingDetail(
        ilan_no=req.ilan_no, url=service.safe_listing_url(req.url) or "", baslik=mask_phones(req.baslik),
        fiyat=req.fiyat, yil=req.yil, km=req.km, il=req.il or "Bilinmiyor", ilce=req.ilce,
        ilan_tarihi=date.today(), marka=marka or "", model=model or "", seri=req.seri, paket=req.paket,
        vites=req.vites, yakit=req.yakit, kasa_tipi=req.kasa_tipi, motor_hacmi=req.motor_hacmi, renk=req.renk,
        kimden=req.kimden, agir_hasar_kayitli=req.agir_hasar_kayitli,
        tramer_tutari_yapilandirilmis=req.tramer_tutari_yapilandirilmis, parts=req.parts,
        aciklama=mask_phones(req.aciklama), fetched_at=datetime.now(timezone.utc), raw_html_path=None)


def _llm_budget_ok(db: Session, detail: ListingDetail) -> bool:
    """Önbellekte varsa LLM maliyeti yoktur; yoksa günlük üst sınır denetlenir."""
    if description_llm.get_cached_findings(db, detail.ilan_no, detail.aciklama, settings.llm_model_fast):
        return True
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    return db.query(LLMCache).filter(LLMCache.fetched_at >= since).count() < settings.analyze_daily_limit


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


# ------------------------------------------------------------------ uç noktalar
@router.get("/ping")
def ping():
    return {"ok": True, "surum": 1, "llm_gunluk_sinir": settings.analyze_daily_limit}


@router.post("/analyze")
def analyze(req: AnalyzeRequest, db: Session = Depends(get_db), llm=Depends(get_llm)):
    detail = build_detail(req, db)
    if not _llm_budget_ok(db, detail):
        raise HTTPException(status_code=429, detail="Günlük LLM analiz sınırı doldu")
    repo.create_or_update_listing(db, detail)
    outcome = pipeline.evaluate_detail(db, llm, detail, req.max_butce)
    v = outcome.verdict
    kanitlar, vurgu = _kanitlar(outcome.findings)
    piyasa = v.piyasa
    return {
        "ilan_no": detail.ilan_no, "beklemede": bool(v.beklemede), "etiket": None if v.beklemede else v.etiket,
        "skor": v.guven_skoru, "veri_tamlik": v.veri_tamlik, "hard_fails": v.hard_fails, "artilar": v.artilar,
        "eksiler": v.eksiler, "trace": v.trace,
        "piyasa": {"n": piyasa.n, "medyan": piyasa.medyan, "guven": piyasa.guven} if piyasa else None,
        "sapma_yuzde": _sapma(detail.fiyat, piyasa.medyan if piyasa else None),
        "tavsiye_teklif": v.tavsiye_teklif, "ust_sinir": v.ust_sinir,
        "ekspertiz_kontrol_listesi": v.ekspertiz_kontrol_listesi, "kanitlar": kanitlar, "vurgu": vurgu,
        "whatsapp_metni": whatsapp_text(detail, v), "marka": detail.marka or None, "model": detail.model or None,
        "uyari": UYARI,
    }


def rozet(sapma: float | None, n: int, rules: dict) -> tuple[str, str]:
    """Liste rozeti: YALNIZ fiyata dair, nötr dil. Karar etiketi değildir."""
    et, bt = rules["etiket"], rules["bantlar"]
    if sapma is None or n < et["min_emsal"]:
        return "emsal_yetersiz", f"Emsal yetersiz (n={n})"
    s = sapma / 100
    if s < bt["sapma_ucuz_uyari"]:
        return "cok_ucuz_suphe", f"⚠ %{abs(sapma):.0f} ucuz: önce nedenini sor"
    if s <= et["alinir_max_sapma"]:
        return "avantajli", f"Fiyat avantajlı (-%{abs(sapma):.0f})"
    if s > rules["rozet"]["pahali_esik"]:
        return "pahali", f"Pahalı (+%{sapma:.0f})"
    return "piyasada", "Piyasa değerinde"


@router.post("/batch-evaluate")
def batch_evaluate(req: BatchRequest, db: Session = Depends(get_db)):
    rules = load_rules()
    now = datetime.now(timezone.utc)
    resolved = {}
    for it in req.items:
        resolved[it.ilan_no] = identify.resolve(it.marka, it.model, it.baslik, req.page_path, db)
    kaydedilen = 0
    if req.remember:
        for it in req.items:
            marka, model = resolved[it.ilan_no]
            if marka and model:      # kimliği belli olmayan ilan piyasa kümesini kirletmesin
                repo.create_or_update_listing_summary(db, ListingSummary(
                    ilan_no=it.ilan_no, url=service.safe_listing_url(it.url) or "", baslik=mask_phones(it.baslik or ""),
                    fiyat=it.fiyat, yil=it.yil, km=it.km, il=it.il or "Bilinmiyor", ilan_tarihi=date.today()),
                    marka, model)
                kaydedilen += 1
    sonuc = []
    for it in req.items:
        marka, model = resolved[it.ilan_no]
        yas = max(now.year - it.yil, 1)
        yillik = round(it.km / yas)
        km_uyari = yillik > rules["hard_fails"]["max_yillik_km"]
        if not (marka and model):
            kod, metin, n, medyan, sapma = "emsal_yetersiz", "Model tanınamadı", 0, None, None
        else:
            d = ListingDetail(ilan_no=it.ilan_no, url="", baslik=it.baslik or "", fiyat=it.fiyat, yil=it.yil,
                              km=it.km, il="", ilan_tarihi=date.today(), marka=marka, model=model, aciklama="",
                              fetched_at=now)
            st = market.get_market_stats(db, d)
            n, medyan = st.n, (st.medyan or None)
            sapma = _sapma(it.fiyat, medyan)
            kod, metin = rozet(sapma, n, rules)
        sonuc.append({"ilan_no": it.ilan_no, "rozet": kod, "rozet_metin": metin, "sapma_yuzde": sapma,
                      "emsal_n": n, "emsal_medyan": medyan, "yillik_km": yillik, "km_uyari": km_uyari,
                      "marka": marka, "model": model})
    return {"sonuclar": sonuc, "kaydedilen": kaydedilen, "uyari": "Rozetler yalnız fiyata dairdir; karar değildir."}
