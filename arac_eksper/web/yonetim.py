"""otoXray yönetim sayfası (/yonetim): üye ekle, hak/bitiş belirle, durdur/iptal, cihazları sıfırla, davet gönder,
kullanımı ve geri bildirimleri gör. Giriş: ADMIN_EMAILS listesindeki adrese e-posta kodu (şifre yok).
Oturum: DB'de özetli kimlik, HttpOnly + Secure + SameSite=Strict çerez (yalnız /yonetim). Değiştirici her istek CSRF
jetonu + Origin denetimi ister. Ekrana kullanıcı girdisi yansıtılmaz; bildirimler sabit kodlardır."""
import hmac
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, mailer, security

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates" / "yonetim"))   # otomatik kaçış açık
router = APIRouter(prefix="/yonetim", include_in_schema=False)
COOKIE = "oxr_yonetim"

MESAJ = {
    "kod": ("ok", "Adres yönetici listesindeyse giriş kodu gönderildi."),
    "kod_hatali": ("err", "Kod hatalı ya da süresi dolmuş."),
    "cok_istek": ("err", "Çok fazla deneme. Biraz sonra tekrar deneyin."),
    "smtp_yok": ("err", "E-posta gönderimi yapılandırılmamış (SMTP ayarları)."),
    "eklendi": ("ok", "Üye eklendi."),
    "eklendi_davet": ("ok", "Üye eklendi ve davet e-postası gönderildi."),
    "eklendi_davetsiz": ("warn", "Üye eklendi ama davet e-postası gönderilemedi; nedeni aşağıda."),
    "davet": ("ok", "Davet e-postası yeniden gönderildi."),
    "davet_hata": ("err", "Davet e-postası gönderilemedi."),
    "guncellendi": ("ok", "Haklar güncellendi."),
    "durum": ("ok", "Üyenin durumu değiştirildi."),
    "cihaz": ("ok", "Üyenin tüm cihazlarındaki oturum kapatıldı; yeniden kodla girmesi gerekir."),
    "email_gecersiz": ("err", "E-posta adresi geçersiz."),
    "email_var": ("err", "Bu e-posta zaten kayıtlı."),
    "deger_gecersiz": ("err", "Değerlerden biri geçersiz (hak sayısı ya da tarih)."),
    "bulunamadi": ("err", "Üye bulunamadı."),
    "form_gecersiz": ("err", "Form doğrulanamadı; işlem yapılmadı. Sayfayı yenileyip tekrar deneyin."),
    "oturum": ("err", "Oturumunuz sona erdi; yeniden giriş yapın."),
}
DURUM_ETIKET = {"aktif": "Aktif", "durduruldu": "Durduruldu", "iptal": "İptal"}

_ips: dict[str, deque] = {}


def _ip_ok(request: Request, limit: int = 20) -> bool:
    now, q = time.time(), _ips.setdefault(security.client_ip(request), deque())
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _admins() -> set[str]:
    out = set()
    for e in settings.admin_emails:
        try:
            out.add(accounts.normalize_email(e))
        except ValueError:
            pass
    return out


def _session(request: Request) -> dict | None:
    return accounts.get_admin_session(request.cookies.get(COOKIE))


def _go(path: str, m: str | None = None) -> RedirectResponse:
    return RedirectResponse(f"/yonetim{path}" + (f"?m={m}" if m else ""), status_code=303)


def _page(request: Request, name: str, sess: dict | None, **ctx) -> Response:
    m = MESAJ.get(request.query_params.get("m", ""))
    return templates.TemplateResponse(request, name, {"sess": sess, "csrf": sess["csrf"] if sess else "",
                                                       "mesaj": m, "durum_etiket": DURUM_ETIKET, **ctx})


def _csrf_ok(request: Request, sess: dict | None, token: str) -> bool:
    return bool(sess) and security.origin_ok(request) and hmac.compare_digest(token or "", sess["csrf"])


def _reject(sess: dict | None) -> RedirectResponse:
    """Form doğrulanamadı: oturum varsa açık uyarıyla geri dön (sessizce yutma)."""
    return _go("", "form_gecersiz") if sess else _go("/giris", "oturum")


def _send_invite(m: dict) -> bool:
    try:
        mailer.send_invite(m["email"], m["ad"], haklar_metni(m), mailer.haklar_kalemleri(m))
    except mailer.MailUnavailable as e:
        accounts.record_invite(m["id"], False, str(e))
        return False
    accounts.record_invite(m["id"], True)
    return True


def haklar_metni(m: dict) -> str:
    parts = [f"günde {m['gunluk_kota']} analiz"]
    if m.get("aylik_kota") is not None:
        parts.append(f"ayda en fazla {m['aylik_kota']}")
    parts.append(f"{m['bitis']} tarihine kadar" if m.get("bitis") else "süre sınırı yok")
    return ", ".join(parts)


# ------------------------------------------------------------------ giriş
STATIC = {"yonetim.css": "text/css", "cg.svg": "image/svg+xml", "favicon-32.png": "image/png", "mail-logo.png": "image/png",
          "fonts/inter-latin.woff2": "font/woff2", "fonts/inter-latin-ext.woff2": "font/woff2",
          "fonts/space-grotesk-latin.woff2": "font/woff2", "fonts/space-grotesk-latin-ext.woff2": "font/woff2"}


@router.get("/static/{name:path}")
def static(name: str):
    """Yalnız beyaz listedeki dosyalar (yol gezintisi yok)."""
    if name not in STATIC:
        return Response(status_code=404)
    return FileResponse(BASE / "static" / name, media_type=STATIC[name],
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/giris")
def giris_form(request: Request):
    if _session(request):
        return _go("")
    return _page(request, "giris.html", None, adim="email", email="")


@router.post("/giris")
def giris_kod(request: Request, email: str = Form("", max_length=254)):
    if not _ip_ok(request):
        return _go("/giris", "cok_istek")
    try:
        e = accounts.normalize_email(email)
    except ValueError:
        return _go("/giris", "email_gecersiz")
    if not mailer.configured():
        return _go("/giris", "smtp_yok")
    if e in _admins():
        code = accounts.create_code(e, "yonetim")
        if code:
            try:
                mailer.send_code(e, code, yonetim=True)
            except mailer.MailUnavailable:
                return _go("/giris", "smtp_yok")
    # adres yönetici listesinde olsun olmasın aynı ekran: listenin içeriği dışarıdan anlaşılmaz
    return templates.TemplateResponse(request, "giris.html", {"sess": None, "csrf": "", "mesaj": MESAJ["kod"],
                                                              "durum_etiket": DURUM_ETIKET, "adim": "kod", "email": e})


@router.post("/dogrula")
def giris_dogrula(request: Request, email: str = Form("", max_length=254), kod: str = Form("", max_length=6)):
    ip = security.client_ip(request)
    if security.login_blocked(ip):
        return _go("/giris", "cok_istek")
    try:
        e = accounts.normalize_email(email)
    except ValueError:
        return _go("/giris", "email_gecersiz")
    if e not in _admins() or not accounts.verify_code(e, "yonetim", kod):
        security.record_fail(ip)
        return _go("/giris", "kod_hatali")
    sid, _ = accounts.new_admin_session(e)
    resp = _go("")
    resp.set_cookie(COOKIE, sid, max_age=12 * 3600, path="/yonetim", httponly=True,
                    secure=settings.admin_cookie_secure, samesite="strict")
    return resp


@router.post("/cikis")
def cikis(request: Request, csrf: str = Form("")):
    sess = _session(request)
    if _csrf_ok(request, sess, csrf):
        accounts.drop_admin_session(request.cookies.get(COOKIE))
    resp = _go("/giris")
    resp.delete_cookie(COOKIE, path="/yonetim")
    return resp


# ------------------------------------------------------------------ üyeler
@router.get("")
def uyeler(request: Request):
    sess = _session(request)
    if not sess:
        return _go("/giris")
    members = accounts.list_members()
    for m in members:
        m["erisim_sorunu"] = accounts.access_problem(m)
    ozet = {"toplam": len(members), "aktif": sum(1 for m in members if not m["erisim_sorunu"]),
            "bugun": sum(m["bugun"] for m in members), "bu_ay": sum(m["bu_ay"] for m in members),
            "geri_bildirim": sum(m["geri_bildirim"] for m in members)}
    return _page(request, "uyeler.html", sess, uyeler=members, ozet=ozet, varsayilan_gunluk=settings.user_daily_quota,
                 smtp=mailer.configured())


def _form_haklar(gunluk: str, aylik: str, bitis: str, rozet: str | None, ad: str, notu: str) -> dict:
    return {"ad": ad, "gunluk_kota": int(gunluk), "aylik_kota": aylik or None, "bitis": bitis or None,
            "rozet": bool(rozet), "notu": notu}


@router.post("/uye")
def uye_ekle(request: Request, csrf: str = Form(""), email: str = Form("", max_length=254),
             ad: str = Form("", max_length=60), gunluk: str = Form("30", max_length=6),
             aylik: str = Form("", max_length=7), bitis: str = Form("", max_length=10),
             rozet: str | None = Form(None), notu: str = Form("", max_length=300), davet: str | None = Form(None)):
    sess = _session(request)
    if not _csrf_ok(request, sess, csrf):
        return _reject(sess)
    try:
        accounts.normalize_email(email)
    except ValueError:
        return _go("", "email_gecersiz")
    if accounts.get_member_by_email(email):
        return _go("", "email_var")
    try:
        mid = accounts.create_member(email, **_form_haklar(gunluk, aylik, bitis, rozet, ad, notu))
    except ValueError:
        return _go("", "deger_gecersiz")
    if not davet:
        return _go("", "eklendi")
    return _go("/davetler", "eklendi_davet" if _send_invite(accounts.get_member(mid)) else "eklendi_davetsiz")


@router.get("/uye/{mid}")
def uye_detay(request: Request, mid: int):
    sess = _session(request)
    if not sess:
        return _go("/giris")
    m = next((x for x in accounts.list_members() if x["id"] == mid), None)
    if not m:
        return _go("", "bulunamadi")
    m["erisim_sorunu"] = accounts.access_problem(m)
    fb = [f for f in accounts.list_feedback(500) if f["member_id"] == mid][:50]
    return _page(request, "uye.html", sess, uye=m, geri_bildirim=fb, haklar=haklar_metni(m))


@router.post("/uye/{mid}")
def uye_guncelle(request: Request, mid: int, csrf: str = Form(""), ad: str = Form("", max_length=60),
                 gunluk: str = Form("30", max_length=6), aylik: str = Form("", max_length=7),
                 bitis: str = Form("", max_length=10), rozet: str | None = Form(None),
                 notu: str = Form("", max_length=300)):
    sess = _session(request)
    if not _csrf_ok(request, sess, csrf):
        return _reject(sess)
    try:
        ok = accounts.update_member(mid, **_form_haklar(gunluk, aylik, bitis, rozet, ad, notu))
    except ValueError:
        return _go(f"/uye/{mid}", "deger_gecersiz")
    return _go(f"/uye/{mid}", "guncellendi" if ok else "bulunamadi")


@router.post("/uye/{mid}/durum")
def uye_durum(request: Request, mid: int, csrf: str = Form(""), durum: str = Form("")):
    sess = _session(request)
    if not _csrf_ok(request, sess, csrf):
        return _reject(sess)
    try:
        ok = accounts.set_status(mid, durum)
    except ValueError:
        return _go(f"/uye/{mid}", "deger_gecersiz")
    return _go(f"/uye/{mid}", "durum" if ok else "bulunamadi")


@router.post("/uye/{mid}/cihazlar")
def uye_cihazlar(request: Request, mid: int, csrf: str = Form("")):
    sess = _session(request)
    if not _csrf_ok(request, sess, csrf):
        return _reject(sess)
    accounts.revoke_all_keys(mid)
    return _go(f"/uye/{mid}", "cihaz")


@router.post("/uye/{mid}/davet")
def uye_davet(request: Request, mid: int, csrf: str = Form("")):
    sess = _session(request)
    if not _csrf_ok(request, sess, csrf):
        return _reject(sess)
    m = accounts.get_member(mid)
    if not m:
        return _go("", "bulunamadi")
    back = "/davetler" if request.query_params.get("geri") == "davetler" else f"/uye/{mid}"
    return _go(back, "davet" if _send_invite(m) else "davet_hata")


@router.get("/geri-bildirim")
def geri_bildirim(request: Request):
    sess = _session(request)
    if not sess:
        return _go("/giris")
    return _page(request, "geri_bildirim.html", sess, kayitlar=accounts.list_feedback(300))


@router.get("/davetler")
def davetler(request: Request):
    sess = _session(request)
    if not sess:
        return _go("/giris")
    rows = accounts.list_invites()
    for r in rows:
        r["erisim_sorunu"] = accounts.access_problem(r)
    ozet = {"toplam": len(rows), "katilan": sum(1 for r in rows if r["ilk_giris"]),
            "hatali": sum(1 for r in rows if not r["son_ok"])}
    return _page(request, "davetler.html", sess, davetler=rows, ozet=ozet, smtp=mailer.configured())
