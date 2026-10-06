"""Jeff için yönetici API'si (/admin-api/v1): yönetim sayfasının yaptığı her şey, JSON olarak.

Erişim üç katmanla sınırlıdır:
  1. Yalnız sunucunun kendi içinden: istemci 127.0.0.1/::1 olmalı ve istekte ters vekil başlığı (X-Forwarded-For,
     X-Real-IP, Forwarded) bulunmamalı. nginx bu yolu dışarı açmaz; açsa bile vekil başlığı yüzünden reddedilir.
  2. Ayrı anahtar: `ADMIN_API_TOKEN` (en az 32 karakter; eklentinin anahtarından farklı). Ayarlı değilse API yoktur (404).
  3. Her DEĞİŞTİRİCİ işlem `admin_log` tablosuna yazılır (kim, ne, kime); okunabilir: GET /islem-kaydi.
İlan verisi burada da yoktur: yalnız hesaplar, haklar, sayaçlar ve geri bildirim.
"""
import hmac
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, mailer

AKTOR = "jeff-api"
_VEKIL = ("x-forwarded-for", "x-real-ip", "forwarded")


def jeff_yetkisi(request: Request) -> None:
    tok = settings.admin_api_token or ""
    if len(tok) < 32:
        raise HTTPException(status_code=404)                       # yapılandırılmamışsa API yok sayılır
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1") or any(h in request.headers for h in _VEKIL):
        raise HTTPException(status_code=404)                       # dışarıdan (vekil üzerinden) gelen istek
    auth = request.headers.get("authorization", "")
    if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), tok.encode())):
        raise HTTPException(status_code=401, detail="Yetkisiz", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/admin-api/v1", dependencies=[Depends(jeff_yetkisi)], include_in_schema=False)


def _uye(ref: str) -> dict:
    m = accounts.get_member(int(ref)) if ref.isdigit() else accounts.get_member_by_email(ref)
    if not m:
        raise HTTPException(status_code=404, detail="Üye bulunamadı")
    return m


def _gorunum(m: dict) -> dict:
    """Üye özeti: hesap alanları + bugünkü/aylık kullanım + erişim sorunu (anahtar özetleri dahil edilmez)."""
    satir = next((x for x in accounts.list_members() if x["id"] == m["id"]), m)
    return {k: satir.get(k) for k in ("id", "email", "ad", "durum", "gunluk_kota", "aylik_kota", "bitis", "rozet", "notu",
                                      "created_at", "son_kullanim", "bugun", "bu_ay", "geri_bildirim", "cihaz")
            if k in satir} | {"erisim_sorunu": accounts.access_problem(satir)}


def _davet(m: dict) -> bool:
    from arac_eksper.web import yonetim
    return yonetim._send_invite(m)


# ------------------------------------------------------------------ okuma
@router.get("/saglik")
def saglik():
    return {"ok": True, "smtp": mailer.configured(), "llm": bool(settings.llm_api_key and settings.llm_base_url),
            "adres": settings.public_url, "bugun": date.today().isoformat()}


@router.get("/ozet")
def ozet():
    uyeler = accounts.list_members()
    k = accounts.kalibrasyon()
    return {"uye": {"toplam": len(uyeler), "erisimi_acik": sum(1 for m in uyeler if not accounts.access_problem(m)),
                    "durum": {d: sum(1 for m in uyeler if m["durum"] == d) for d in ("aktif", "durduruldu", "iptal")}},
            "kullanim": {"bugun": sum(m["bugun"] for m in uyeler), "bu_ay": sum(m["bu_ay"] for m in uyeler)},
            "geri_bildirim": sum(m["geri_bildirim"] for m in uyeler),
            "kalibrasyon": {"sonuclu": k["toplam"], "ekspertizli": k["ekspertizli"], "yesil_isabet": k["yesil_isabet"],
                            "yanlis_yesil": len(k["yanlis_yesil"]), "kacan_aday": len(k["kacan"])}}


@router.get("/uyeler")
def uyeler():
    return {"uyeler": [_gorunum(m) for m in accounts.list_members()]}


@router.get("/uyeler/{ref}")
def uye(ref: str):
    m = _uye(ref)
    fb = [f for f in accounts.list_feedback(500) if f["member_id"] == m["id"]][:50]
    return {"uye": _gorunum(m), "geri_bildirim": fb}


@router.get("/geri-bildirim")
def geri_bildirim(limit: int = 100):
    return {"kayitlar": accounts.list_feedback(max(1, min(limit, 500)))}


@router.get("/kalibrasyon")
def kalibrasyon():
    return accounts.kalibrasyon()


@router.get("/davetler")
def davetler():
    return {"davetler": accounts.list_invites()}


@router.get("/islem-kaydi")
def islem_kaydi(limit: int = 100):
    return {"kayitlar": accounts.list_admin_log(max(1, min(limit, 500)))}


# ------------------------------------------------------------------ değiştirici (hepsi kayda geçer)
class UyeEkle(BaseModel):
    email: str = Field(max_length=254)
    ad: str | None = Field(None, max_length=60)
    gunluk_kota: int | None = Field(None, ge=0, le=10_000)
    aylik_kota: int | None = Field(None, ge=0, le=300_000)
    bitis: date | None = None
    rozet: bool = True
    notu: str | None = Field(None, max_length=300)
    davet: bool = True


class UyeGuncelle(BaseModel):
    ad: str | None = Field(None, max_length=60)
    gunluk_kota: int | None = Field(None, ge=0, le=10_000)
    aylik_kota: int | None = Field(None, ge=0, le=300_000)
    bitis: date | None = None
    rozet: bool | None = None
    notu: str | None = Field(None, max_length=300)


class Durum(BaseModel):
    durum: str = Field(pattern=r"^(aktif|durduruldu|iptal)$")


@router.post("/uyeler", status_code=201)
def uye_ekle(req: UyeEkle):
    try:
        e = accounts.normalize_email(req.email)
    except ValueError:
        raise HTTPException(status_code=422, detail="E-posta adresi geçersiz")
    if accounts.get_member_by_email(e):
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")
    alanlar = req.model_dump(exclude={"email", "davet"})
    alanlar["bitis"] = req.bitis.isoformat() if req.bitis else None
    try:
        mid = accounts.create_member(e, **alanlar)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    davet = _davet(accounts.get_member(mid)) if req.davet else None
    accounts.log_admin(AKTOR, "uye_ekle", e, f"davet={'gonderildi' if davet else 'yok' if davet is None else 'basarisiz'}")
    return {"uye": _gorunum(accounts.get_member(mid)), "davet_gonderildi": davet}


@router.patch("/uyeler/{ref}")
def uye_guncelle(ref: str, req: UyeGuncelle):
    m = _uye(ref)
    alanlar = req.model_dump(exclude_unset=True)
    if "bitis" in alanlar:
        alanlar["bitis"] = alanlar["bitis"].isoformat() if alanlar["bitis"] else None
    if not alanlar:
        raise HTTPException(status_code=422, detail="Değiştirilecek alan yok")
    try:
        accounts.update_member(m["id"], **alanlar)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    accounts.log_admin(AKTOR, "uye_guncelle", m["email"], ", ".join(f"{k}={v}" for k, v in alanlar.items() if k != "notu"))
    return {"uye": _gorunum(accounts.get_member(m["id"]))}


@router.post("/uyeler/{ref}/durum")
def uye_durum(ref: str, req: Durum):
    m = _uye(ref)
    accounts.set_status(m["id"], req.durum)
    accounts.log_admin(AKTOR, "uye_durum", m["email"], req.durum)
    return {"uye": _gorunum(accounts.get_member(m["id"]))}


@router.post("/uyeler/{ref}/cihazlari-kapat")
def uye_cihazlar(ref: str):
    m = _uye(ref)
    n = accounts.revoke_all_keys(m["id"])
    accounts.log_admin(AKTOR, "cihazlari_kapat", m["email"], f"{n} anahtar")
    return {"kapatilan_anahtar": n}


@router.post("/uyeler/{ref}/davet")
def uye_davet(ref: str):
    m = _uye(ref)
    ok = _davet(m)
    accounts.log_admin(AKTOR, "davet", m["email"], "gonderildi" if ok else "basarisiz")
    return {"davet_gonderildi": ok}
