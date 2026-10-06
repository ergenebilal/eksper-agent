"""CyberOto AI uç noktaları (/api/v1). İLAN VERİSİ AÇISINDAN DURUMSUZ: ilan metni, başlık, bağlantı ya da karar sunucuda
SAKLANMAZ; ilan önbelleği ve günlük kaydı yoktur, her istek bellekte işlenir. Tek kalıcı kayıt davetli kullanıcı hesabıdır
(web/accounts.py: e-postaya bağlı üye ve hakları, anahtar/kod özetleri, sayaçlar, kullanıcının bilerek gönderdiği geri
bildirim); sahip anahtarı ona da dokunmaz.
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

from arac_eksper.analysis import (checklist, description_llm, market_calc, masraf, offer as offer_calc, rehber, rules_engine,
                                  likidite, sinyaller)
from arac_eksper.config.rules_loader import load_rules
from arac_eksper.config.settings import settings
from arac_eksper.llm.client import LLMUnavailable, OpenAIClient
from arac_eksper.privacy import mask_phones
from arac_eksper.report.legal import DISCLAIMER
from arac_eksper.report.offer_text import whatsapp_text
from arac_eksper.schemas import DescriptionFindings, ListingDetail, MarketStats, PartState, Verdict
from arac_eksper.web import accounts, mailer, security

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
    ilan_tarihi: date | None = None                       # sayfadaki "İlan Tarihi"
    kimden: str | None = Field(None, max_length=30)       # satıcı türü: bireysel / galeri (ilan niteliği, kişi değil)
    fiyat_degisti: bool | None = None                     # sitenin fiyat değişim bayrağı
    gorulen_dusus: int | None = Field(None, ge=0, le=500_000_000)   # kullanıcının KENDİ gördüğü fiyat düşüşü (havuz)
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


def _take(user: dict, tur: str, limit: int | None, monthly: int | None = None) -> None:
    """Üyenin günlük (ve verildiyse aylık) hakkından düşer; sahip (id 0) hesap deposuna hiç dokunmaz."""
    if user["id"] and not accounts.consume(user["id"], limit, tur, monthly):
        if monthly is not None and accounts.used_month(user["id"], tur) >= monthly:
            raise HTTPException(status_code=429, detail=f"Bu ayki hakkınız doldu ({monthly}). Ay başında yenilenir.")
        raise HTTPException(status_code=429, detail=f"Günlük hakkınız doldu ({limit}). Yarın yenilenir.")


def _kota(user: dict) -> dict | None:
    """Üyenin hakları: günlük (limit/kullanilan, eklenti bunu gösterir), aylık, bitiş, rozet."""
    if not user["id"]:
        return None
    aylik = user.get("aylik_kota")
    return {"limit": user["gunluk_kota"], "kullanilan": accounts.used_today(user["id"]),
            "aylik": None if aylik is None else {"limit": aylik, "kullanilan": accounts.used_month(user["id"])},
            "bitis": user.get("bitis"), "rozet": bool(user.get("rozet", 1))}


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
            # aynı alıntı olumsuz sinyal olarak zaten varsa iki kez gösterme: daha özgül (hard-claim) etiketi kalır
            ayni = next((k for k in out if description_llm._match_key(k["alinti"]) == description_llm._match_key(alinti)), None)
            if ayni:
                ayni.update(tur="olumsuz", etiket=etiket)
            else:
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


def _sinyaller(req: AnalyzeRequest, detail: ListingDetail) -> dict:
    """R4.1/R4.2: satış motivasyonu bandı + ticari dil sinyali (LLM'siz, alıntılı; hak harcamaz)."""
    text = f"{detail.baslik}\n{detail.aciklama}"
    ayni_seri = sum(1 for c in req.emsal if (c.seri or "").lower() == (req.seri or "").lower()) if req.seri else None
    return {"satis": sinyaller.satis_motivasyonu(text, req.ilan_tarihi, req.fiyat_degisti, req.gorulen_dusus or 0),
            "ticari": sinyaller.ticari_dil(text, req.kimden),
            "likidite": likidite.likidite(req.model_dump(include={"marka", "seri", "yakit", "vites", "kasa_tipi",
                                                                  "motor_hacmi", "yil"}), ayni_seri, req.ilan_tarihi)}


def _pending(req: AnalyzeRequest) -> dict:
    return {"ilan_no": req.ilan_no, "beklemede": True, "etiket": None, "skor": 0.0, "veri_tamlik": 0.0,
            "hard_fails": [], "artilar": [], "eksiler": ["LLM analizi bekliyor (havuza erişilemedi)"], "trace": [],
            "piyasa": None, "sapma_yuzde": None, "tavsiye_teklif": None, "ust_sinir": None,
            "ekspertiz_kontrol_listesi": [], "kanitlar": [], "vurgu": [], "whatsapp_metni": None,
            "uyari": NOT, "yasal_uyari": DISCLAIMER}


# ------------------------------------------------------------------ uç noktalar
@router.get("/ping")
def ping(user=Depends(current_user)):
    return {"ok": True, "surum": 3, "durumsuz": True, "kullanici": user.get("email") or user["ad"], "kota": _kota(user),
            "yasal_uyari": DISCLAIMER}


@router.get("/rehber")
def rehber_icerik():
    """Onaylı statik rehberler (alım günü / noter listesi). Onaylanmamışsa null: panel bölümü göstermez."""
    return {"alim_gunu": rehber.load_alim_gunu()}


@router.post("/quick")
def quick(req: AnalyzeRequest, user=Depends(current_user)):
    """LLM'siz ANINDA ön hesap: piyasa, yapıdan elenme nedenleri ve ön teklif. LLM röntgeni beklenirken gösterilir;
    etiket ÜRETMEZ (açıklama analizi olmadan karar verilmez). LLM bütçesinden düşmez, hiçbir şey saklanmaz."""
    _take(user, "quick", settings.user_daily_batch)
    tekrar = bool(user["id"]) and accounts.charged_recently(user["id"], accounts.listing_hash(req.ilan_no, req.aciklama))
    detail, sema_uyari = rules_engine.sema_kontrolu(_detail(req))
    stats = market_calc.stats_from_comparables(req.ilan_no, req.yil, req.km, _comps(req.emsal), req.seri)
    empty = DescriptionFindings(sase_direk_podye_islem="belirsiz", airbag="belirsiz", motor_sanziman="belirsiz",
                                km_degisimi_suphesi=False)
    rules = load_rules()
    hard = rules_engine.evaluate_hard_fails(detail, empty, stats, rules, req.max_butce)
    pending = Verdict(ilan_no=req.ilan_no, etiket="DUSUNULEBILIR", guven_skoru=0.0, veri_tamlik=0.0, piyasa=stats)
    gm = masraf.gercek_maliyet(detail)
    sg = _sinyaller(req, detail)
    b = None if hard else sinyaller.teklife_uygula(
        masraf.teklife_uygula(offer_calc.breakdown(detail, empty, pending, allow_no_market=True), gm), sg["satis"])
    return {"ilan_no": req.ilan_no, "on_hesap": True, "elenme_nedenleri": hard, "gercek_maliyet": gm,
            "piyasa": {"n": stats.n, "medyan": stats.medyan, "p25": stats.p25, "p75": stats.p75, "guven": stats.guven,
                       "min_emsal": rules["etiket"]["min_emsal"]},
            "sapma_yuzde": _sapma(req.fiyat, stats.medyan), "teklif": b, "yasal_uyari": DISCLAIMER,
            "kota": _kota(user), "tekrar_ucretsiz": tekrar, "sema_uyarisi": sema_uyari, "sinyaller": sg}


@router.post("/analyze")
def analyze(req: AnalyzeRequest, llm=Depends(get_llm), user=Depends(current_user)):
    # Hak yalnız YENİ analizde düşer: aynı ilan + aynı açıklama 7 gün içinde (yeniden analiz, başka cihaz) ücretsiz
    h = accounts.listing_hash(req.ilan_no, req.aciklama)
    charge = bool(user["id"]) and not accounts.charged_recently(user["id"], h)
    if charge:
        _take(user, "analyze", user["gunluk_kota"], user.get("aylik_kota"))
    if not _llm_budget_ok():
        if charge:
            accounts.refund(user["id"])
        raise HTTPException(status_code=429, detail="Sunucunun günlük analiz sınırı doldu")
    detail = _detail(req)
    stats = market_calc.stats_from_comparables(req.ilan_no, req.yil, req.km, _comps(req.emsal), req.seri)
    try:
        findings = description_llm.analyze_description(llm, detail.baslik, detail.aciklama,    # db yok → önbellek yok
                                                      second_pass=settings.xray_second_pass)
    except (LLMUnavailable, ValueError):       # pydantic.ValidationError bir ValueError'dır
        if charge:
            accounts.refund(user["id"])         # analiz yapılamadıysa hak yanmaz
        return _pending(req)
    if charge:
        accounts.add_charge(user["id"], h)
    v = rules_engine.determine_verdict(detail, findings, stats, max_butce=req.max_butce)
    # Açıklamalı teklif: piyasa varsa piyasadan, yoksa YALNIZ ilan fiyatından (kaynak="ilan", düşük güven)
    gm = masraf.gercek_maliyet(detail, llm_kalemler=findings.masraf_kalemleri)
    sg = _sinyaller(req, detail)
    b = sinyaller.teklife_uygula(masraf.teklife_uygula(offer_calc.breakdown(detail, findings, v, allow_no_market=True), gm),
                                 sg["satis"])
    q = sinyaller.soru(sg["ticari"])
    if q:
        v.soru_carsafi = sorted(v.soru_carsafi + [q], key=lambda x: x["oncelik"])[:10]
    if b:
        v.tavsiye_teklif, v.ust_sinir = b["acilis"], b["ust_sinir"]
    kanitlar, vurgu = _kanitlar(findings)
    return {
        "ilan_no": req.ilan_no, "beklemede": False, "etiket": v.etiket, "skor": v.guven_skoru,
        "veri_tamlik": v.veri_tamlik, "hard_fails": v.hard_fails, "artilar": v.artilar, "eksiler": v.eksiler,
        "trace": v.trace if not user["id"] else [],     # kural ağırlıkları yalnız sahibe: davetliden kopyalanamasın
        "piyasa": {"n": stats.n, "medyan": stats.medyan, "p25": stats.p25, "p75": stats.p75, "guven": stats.guven,
                   "min_emsal": load_rules()["etiket"]["min_emsal"]},
        "teklif": b, "gercek_maliyet": gm, "sinyaller": sg,
        "sapma_yuzde": _sapma(req.fiyat, stats.medyan), "tavsiye_teklif": v.tavsiye_teklif, "ust_sinir": v.ust_sinir,
        "ekspertiz_kontrol_listesi": v.ekspertiz_kontrol_listesi, "kanitlar": kanitlar, "vurgu": vurgu,
        "ekspertiz": v.ekspertiz_bolumleri, "soru_carsafi": v.soru_carsafi, "soru_metni": checklist.soru_metni(v.soru_carsafi),
        "whatsapp_metni": whatsapp_text(detail, v), "uyari": NOT, "yasal_uyari": DISCLAIMER, "kota": _kota(user),
        "hak_kullanildi": charge,
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
    if user["id"] and not user.get("rozet", 1):
        raise HTTPException(status_code=403, detail="Arama sayfası fiyat rozetleri hesabınızda kapalı.")
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


@router.post("/cikis")
def cikis(user=Depends(current_user)):
    """Bu cihazın anahtarını iptal eder (eklentide 'Çıkış yap')."""
    if user["id"] and user.get("key_id"):
        accounts.revoke_key(user["key_id"])
    return {"ok": True}


# ------------------------------------------------------------------ e-posta koduyla giriş (anahtar GEREKMEZ)
auth_router = APIRouter(prefix="/api/v1/auth")
_code_ips: dict[str, deque] = {}
_code_ips_lock = threading.Lock()
GENEL_YANIT = "Adres kayıtlı ve erişimi açıksa giriş kodu gönderildi. E-postanızı (gerekirse spam klasörünü) kontrol edin."


class KodRequest(BaseModel):
    email: str = Field(max_length=254)


class GirisRequest(BaseModel):
    email: str = Field(max_length=254)
    kod: str = Field(pattern=r"^\d{6}$")
    cihaz: str | None = Field(None, max_length=60)


def _ip_ok(ip: str, limit: int = 20) -> bool:
    now = time.time()
    with _code_ips_lock:
        q = _code_ips.setdefault(ip, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


@auth_router.post("/kod")
def kod_iste(req: KodRequest, request: Request):
    """Kayıtlı ve erişimi açık üyeye 6 haneli kod gönderir. Yanıt, adresin kayıtlı olup olmadığını SÖYLEMEZ."""
    if not _ip_ok(security.client_ip(request)):
        raise HTTPException(status_code=429, detail="Çok fazla istek. Bir saat sonra tekrar deneyin.")
    try:
        email = accounts.normalize_email(req.email)
    except ValueError:
        raise HTTPException(status_code=422, detail="Geçersiz e-posta adresi") from None
    if not mailer.configured():
        raise HTTPException(status_code=503, detail="E-posta gönderimi henüz açık değil. Yöneticiye haber verin.")
    m = accounts.get_member_by_email(email)
    if m and not accounts.access_problem(m):
        code = accounts.create_code(email, "uye")
        if code:
            try:
                mailer.send_code(email, code)
            except mailer.MailUnavailable:
                raise HTTPException(status_code=503, detail="Kod gönderilemedi, biraz sonra tekrar deneyin.") from None
    return {"ok": True, "mesaj": GENEL_YANIT}


@auth_router.post("/giris")
def giris(req: GirisRequest, request: Request):
    """Doğru kodla bu cihaz için anahtar verir. Yanlış denemeler IP başına sınırlıdır."""
    ip = security.client_ip(request)
    if security.login_blocked(ip):
        raise HTTPException(status_code=429, detail="Çok fazla deneme")
    m = accounts.get_member_by_email(req.email)
    if not m or not accounts.verify_code(req.email, "uye", req.kod):
        security.record_fail(ip)
        raise HTTPException(status_code=401, detail="Kod hatalı ya da süresi dolmuş.")
    problem = accounts.access_problem(m)
    if problem:
        raise HTTPException(status_code=403, detail=problem)
    key = accounts.issue_key(m["id"], req.cihaz)
    m = accounts.find_by_key(key)
    return {"ok": True, "anahtar": key, "email": m["email"], "ad": m["ad"], "kota": _kota(m)}


# ------------------------------------------------------------------ Savaş Odası: karşılaştır ve karar ver (R3.3)
class CompareSonuc(BaseModel):
    """İstemcinin tarayıcısında duran, önceden yapılmış röntgen sonucunun özeti (sunucu saklamaz)."""
    etiket: Literal["ALINIR", "DUSUNULEBILIR", "ALINMAZ"]
    skor: float = Field(ge=0, le=10)
    veri_tamlik: float | None = Field(None, ge=0, le=1)
    hard_fails: list[str] = Field(default_factory=list, max_length=10)
    eksiler: list[str] = Field(default_factory=list, max_length=20)
    artilar: list[str] = Field(default_factory=list, max_length=20)
    sapma_yuzde: float | None = Field(None, ge=-100, le=500)

    @field_validator("hard_fails", "eksiler", "artilar")
    @classmethod
    def _kisa(cls, v):
        return [mask_phones(str(x))[:200] for x in v]


class CompareItem(BaseModel):
    ilan_no: str = Field(pattern=ID_RE)
    baslik: str = Field("", max_length=200)
    fiyat: int = Field(ge=1, le=500_000_000)
    yil: int = Field(ge=1950, le=2100)
    km: int = Field(ge=0, le=3_000_000)
    marka: str | None = Field(None, max_length=60)
    seri: str | None = Field(None, max_length=80)
    paket: str | None = Field(None, max_length=80)
    vites: str | None = Field(None, max_length=40)
    yakit: str | None = Field(None, max_length=40)
    aciklama: str = Field("", max_length=8000)
    ilan_tarihi: date | None = None
    fiyat_degisti: bool | None = None
    gorulen_fiyatlar: list[int] = Field(default_factory=list, max_length=30)
    sonuc: CompareSonuc


class CompareRequest(BaseModel):
    ilanlar: list[CompareItem] = Field(min_length=2, max_length=5)


@router.post("/compare")
def compare(req: CompareRequest, llm=Depends(get_llm), user=Depends(current_user)):
    """2-5 ilanı karşılaştırır. Kararlar kodda; LLM yalnız doğrulanmış gerekçe yazar (yoksa şablon). 1 hak; her ilanın
    tekil röntgeni bu üye tarafından son 7 gün içinde çekilmiş olmalı; aynı küme tekrar ücretsiz. Hiçbir şey saklanmaz
    (yalnız küme özeti hash'i)."""
    from arac_eksper.analysis import compare as cmp
    ids = [i.ilan_no for i in req.ilanlar]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Aynı ilan birden fazla kez seçilmiş.")
    hashes = [accounts.listing_hash(i.ilan_no, mask_phones(i.aciklama)) for i in req.ilanlar]
    if user["id"]:
        for n, (i, h) in enumerate(zip(req.ilanlar, hashes), 1):
            if not accounts.charged_recently(user["id"], h):
                raise HTTPException(status_code=409, detail=f"Önce {n} numaralı ilanın röntgenini çekin (son 7 gün içinde).")
    import hashlib
    kume = "cmp:" + hashlib.sha256("|".join(sorted(hashes)).encode()).hexdigest()
    charge = bool(user["id"]) and not accounts.charged_recently(user["id"], kume)
    if charge:
        _take(user, "analyze", user["gunluk_kota"], user.get("aylik_kota"))
    bugun = date.today()
    items = []
    for i in req.ilanlar:
        d = ListingDetail(ilan_no=i.ilan_no, url="", baslik=mask_phones(i.baslik), fiyat=i.fiyat, yil=i.yil, km=i.km,
                          il="", ilan_tarihi=bugun, marka=i.marka or "", model=i.seri or "", seri=i.seri, paket=i.paket,
                          vites=i.vites, yakit=i.yakit, aciklama=mask_phones(i.aciklama), fetched_at=datetime.now(timezone.utc))
        items.append(dict(i.model_dump(), baslik=d.baslik, gercek_maliyet=masraf.gercek_maliyet(d),
                          sonuc=i.sonuc.model_dump()))
    tablo = [cmp.satir(n, it, bugun) for n, it in enumerate(items, 1)]
    sec = cmp.secimler(tablo)
    anlatim, llm_ok = None, False
    if _llm_budget_ok():
        try:
            anlatim = cmp.llm_anlatim(llm, tablo, sec, settings.llm_model_fast)
            llm_ok = anlatim is not None
        except Exception:                      # gerekçe opsiyoneldir: her hata şablona düşer, kararlar koddadır
            anlatim = None
    anlatim = anlatim or cmp.sablon_anlatim(tablo, sec)
    if charge:
        accounts.add_charge(user["id"], kume)
    return {"tablo": tablo, **sec, "anlatim": anlatim, "llm": llm_ok, "hak_kullanildi": charge, "kota": _kota(user),
            "uyari": "Karşılaştırma ilan verisine dayanır; karar ekspertiz sonrası verilmelidir.", "yasal_uyari": DISCLAIMER}


# ------------------------------------------------------------------ Belge röntgeni: ekspertiz raporu / tramer (R5.4, R5.1)
_TRAMER_YOK = re.compile(r"tramer(?:siz|i?\s*(?:kayd[ıi])?\s*(?:yok|yoktur|bulunmamaktad[ıi]r))|(?<!a[gğ][ıi]r\s)hasar\s+kayd[ıi]\s+(?:yok|yoktur)", re.I)
_TRAMER_TUTAR = re.compile(r"(?:tramer|(?<!a[gğ][ıi]r\s)hasar\s+kayd[ıi])\D{0,25}?(\d{1,3}(?:[.\s]\d{3})+|\d+(?:,\d+)?\s*bin|\d{4,7})", re.I)


def _tramer_beyan(req: "AnalyzeRequest") -> int | None:
    """İlanın tramer beyanı: yapılandırılmış alan, yoksa açıklamadaki 'tramer 18.000' / 'tramersiz' (kurallı)."""
    if req.tramer_tutari_yapilandirilmis is not None:
        return req.tramer_tutari_yapilandirilmis
    text = f"{req.baslik}\n{req.aciklama}"
    if _TRAMER_YOK.search(text):
        return 0
    m = _TRAMER_TUTAR.search(text)
    if m:
        n = description_llm._amounts(m.group(1))
        return max(n) if n else None
    return None


class BelgeRequest(BaseModel):
    tur: Literal["ekspertiz", "tramer"]
    metin: str = Field("", max_length=30_000)
    pdf_b64: str | None = Field(None, max_length=6_000_000)
    gorseller: list[str] = Field(default_factory=list, max_length=4)    # R5.2: fotoğraf / ekran görüntüsü (base64)
    ilan: AnalyzeRequest | None = None

    @field_validator("gorseller")
    @classmethod
    def _boyut(cls, v):
        if any(len(x) > 4_200_000 for x in v):
            raise ValueError("her görsel en fazla 3 MB olabilir")
        return v


def _iade(charge: bool, user: dict) -> None:
    if charge:
        accounts.refund(user["id"])


@router.post("/belge")
def belge(req: BelgeRequest, llm=Depends(get_llm), user=Depends(current_user)):
    """Kullanıcının kendi ekspertiz raporu ya da tramer sorgusu (metin, metin katmanlı PDF ya da fotoğraf/ekran görüntüsü)
    → maskeleme → alıntılı çıkarım → ilanla kurallı karşılaştırma, onarım aralığı, üst sınır önerisi. 1 hak; aynı belge +
    ilan tekrar ücretsiz. Belge ve görsel SAKLANMAZ (yalnız özet hash'i). Görsel, okunmak için LLM sağlayıcısına gider."""
    import hashlib

    from arac_eksper.analysis import belge as bg
    ilan_no = req.ilan.ilan_no if req.ilan else ""
    gorseller, metin = [], req.metin
    if req.gorseller:
        try:
            gorseller = bg.gorseller_coz(req.gorseller)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        ozet = hashlib.sha256("|".join(b for _, b in gorseller).encode()).hexdigest()
    else:
        if req.pdf_b64:
            try:
                metin = bg.pdf_metni(req.pdf_b64)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
        metin = bg.maskele(metin or "")
        if len(metin.strip()) < 40:
            raise HTTPException(status_code=422, detail="Belgede okunabilir metin yok. Taranmış PDF ya da fotoğrafsa "
                                                        "görsel olarak yükleyin.")
        ozet = hashlib.sha256(metin.encode()).hexdigest()
    h = "belge:" + hashlib.sha256(f"{req.tur}|{ilan_no}|{ozet}".encode()).hexdigest()
    charge = bool(user["id"]) and not accounts.charged_recently(user["id"], h)
    if charge:
        _take(user, "analyze", user["gunluk_kota"], user.get("aylik_kota"))
    if not _llm_budget_ok() or (gorseller and not _llm_budget_ok()):      # görsel okuma ayrı bir LLM çağrısıdır
        _iade(charge, user)
        raise HTTPException(status_code=429, detail="Sunucunun günlük analiz sınırı doldu")
    try:
        if gorseller:
            metin = bg.gorselden_metin(llm, gorseller, settings.llm_model_fast)
        b, atilan = bg.cikar(llm, req.tur, metin, settings.llm_model_fast)
    except ValueError as e:
        _iade(charge, user)
        if gorseller and "bulunamadı" in str(e):
            raise HTTPException(status_code=422, detail=f"{e} Hakkınız iade edildi.")
        raise HTTPException(status_code=503, detail="Belge şu an okunamadı; hakkınız iade edildi. Biraz sonra tekrar deneyin.")
    except LLMUnavailable:
        _iade(charge, user)
        raise HTTPException(status_code=503, detail="Belge şu an okunamadı; hakkınız iade edildi. Biraz sonra tekrar deneyin.")
    if charge:
        accounts.add_charge(user["id"], h)
    ilan = None
    if req.ilan:
        ilan = {"fiyat": req.ilan.fiyat, "km": req.ilan.km, "marka": req.ilan.marka, "seri": req.ilan.seri,
                "parts": {k: v.value for k, v in req.ilan.parts.items()}, "agir_hasar_kayitli": req.ilan.agir_hasar_kayitli,
                "tramer_beyan": _tramer_beyan(req.ilan)}
    cel = bg.karsilastir(req.tur, b, ilan)
    mal = bg.maliyet(b, ilan)
    return {"tur": req.tur, "bulgular": b.model_dump(), "dusen_bulgu": atilan, "celiskiler": cel, "maliyet": mal,
            "teklif": bg.teklif(req.tur, b, ilan, mal), "ozet": bg.ozet(req.tur, cel, b),
            "ilan_tramer_beyani": ilan and ilan["tramer_beyan"], "hak_kullanildi": charge, "kota": _kota(user),
            "kaynak": "gorsel" if gorseller else "metin", "okunan_metin": metin if gorseller else None,
            "uyari": ("Belge fotoğraftan yapay zeka ile okundu; okunan metni ve bulguları belgenin aslıyla karşılaştırın."
                      if gorseller else
                      "Belge okuması yapay zeka ile yapıldı; her bulgu belgeden alıntılanır. Belgenin aslıyla karşılaştırın."),
            "yasal_uyari": DISCLAIMER}
