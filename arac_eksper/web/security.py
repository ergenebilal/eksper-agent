"""Panel güvenliği: token doğrulama, sunucu tarafı oturum, CSRF, giriş denemesi sınırı, güvenlik başlıkları.
Token hiçbir yerde loglanmaz ya da şablona verilmez; çerezde yalnızca rastgele oturum kimliği durur."""
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from arac_eksper.config.settings import settings

COOKIE = "arac_session"
MIN_TOKEN_LEN = 16
LOGIN_MAX_FAILS, LOGIN_WINDOW_S = 8, 15 * 60

_sessions: dict[str, dict] = {}        # oturum_id -> {"csrf", "exp"}
_fails: dict[str, list[float]] = {}    # ip -> hata zamanları


def token_problem() -> str | None:
    t = settings.panel_token
    if not t:
        return "PANEL_TOKEN boş: panel başlamaz."
    if len(t) < MIN_TOKEN_LEN:
        return f"PANEL_TOKEN en az {MIN_TOKEN_LEN} karakter olmalı."
    return None


def check_startup() -> None:
    problem = token_problem()
    if problem:
        raise RuntimeError(problem)


def extension_problem() -> str | None:
    t = settings.extension_token
    if not t or len(t) < MIN_TOKEN_LEN:
        return "EXTENSION_TOKEN boş/kısa: eklenti API'si kapalı."
    return None


OWNER = {"id": 0, "ad": "sahip", "email": "sahip", "gunluk_kota": None, "aylik_kota": None, "bitis": None,
         "rozet": 1, "key_id": None}


def require_extension_auth(request: Request) -> dict:
    """/api/v1: Bearer EXTENSION_TOKEN (sahip, kotasız) ya da üyenin cihaz anahtarı (oxr_…, e-posta koduyla alınır,
    kotalı, iptal edilebilir). Çerez kabul edilmez (tarayıcıdan CSRF imkânı olmasın). Kimlik request.state.user'a yazılır.
    Durdurulmuş/süresi dolmuş üye 403 alır (neden metniyle); bu, deneme sınırına sayılmaz."""
    if extension_problem():
        raise HTTPException(status_code=503, detail="Eklenti API'si kapalı (EXTENSION_TOKEN ayarlı değil)")
    h = request.headers.get("authorization", "")
    cand = h[7:].strip() if h[:7].lower() == "bearer " else ""
    user = None
    if cand and hmac.compare_digest(cand.encode(), settings.extension_token.encode()):
        user = OWNER
    elif cand:
        from arac_eksper.web import accounts
        user = accounts.find_by_key(cand)
    if not user:          # geçerli anahtar her zaman geçer; deneme sınırı yalnız başarısız isteklere uygulanır
        ip = client_ip(request)
        if login_blocked(ip):
            raise HTTPException(status_code=429, detail="Çok fazla deneme")
        record_fail(ip)
        raise HTTPException(status_code=401, detail="Yetkisiz", headers={"WWW-Authenticate": "Bearer"})
    if user["id"]:
        from arac_eksper.web import accounts
        problem = accounts.access_problem(user)
        if problem:
            raise HTTPException(status_code=403, detail=problem)
    request.state.user = user
    return user


def host_allowed(request: Request) -> bool:
    host = request.headers.get("host", "")
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0].lstrip("[")
    return name.lower() in {h.lower() for h in settings.panel_allowed_hosts}


def token_matches(candidate: str | None) -> bool:
    if token_problem() or not candidate:
        return False    # token yoksa/zayıfsa hiçbir şey kabul edilmez (fail closed)
    return hmac.compare_digest(candidate.encode(), settings.panel_token.encode())


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def login_blocked(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < LOGIN_WINDOW_S]
    return len(_fails[ip]) >= LOGIN_MAX_FAILS


def record_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def new_session() -> tuple[str, str]:
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    _sessions[sid] = {"csrf": csrf, "exp": time.time() + settings.panel_session_hours * 3600}
    return sid, csrf


def get_session(request: Request) -> dict | None:
    sid = request.cookies.get(COOKIE)
    sess = _sessions.get(sid or "")
    if not sess:
        return None
    if sess["exp"] < time.time():
        _sessions.pop(sid, None)
        return None
    return sess


def drop_session(request: Request) -> None:
    _sessions.pop(request.cookies.get(COOKIE) or "", None)


def bearer_ok(request: Request) -> bool:
    h = request.headers.get("authorization", "")
    return h[:7].lower() == "bearer " and token_matches(h[7:].strip())


def origin_ok(request: Request) -> bool:
    """Tarayıcıdan gelen değiştirici isteklerde istek aynı siteden gelmeli (CSRF ek katmanı; jeton ayrıca zorunlu).
    Referrer-Policy: no-referrer yüzünden Chrome form POST'unda Origin'i "null" gönderir; o durumda tarayıcının
    Sec-Fetch-Site başlığı esas alınır (aynı köken = "same-origin")."""
    site = request.headers.get("sec-fetch-site")
    if site:
        return site in ("same-origin", "none")
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src:
        return True     # tarayıcı dışı istemci (Bearer ile gelen Jeff vb.)
    if src == "null":
        return False    # köken gizlenmiş ve Sec-Fetch-Site yok: güvenli tarafta kal
    return urlsplit(src).netloc == request.headers.get("host", "")


def require_page_auth(request: Request) -> dict:
    sess = get_session(request)
    if not sess:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return sess


def require_api_auth(request: Request) -> None:
    """/v1: Bearer token (Jeff/API) ya da geçerli oturum çerezi (panel). Çerezle yapılan DEĞİŞTİRİCİ istekler
    ayrıca X-CSRF-Token ister (P1'de kullanılacak; P0 yalnızca GET)."""
    if bearer_ok(request):
        return
    sess = get_session(request)
    if sess:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not origin_ok(request) or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), sess["csrf"]):
                raise HTTPException(status_code=403, detail="CSRF doğrulaması başarısız")
        return
    raise HTTPException(status_code=401, detail="Yetkisiz", headers={"WWW-Authenticate": "Bearer"})


SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; "
                                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def harden(app) -> None:
    """Host beyaz listesi (DNS rebinding) + güvenlik başlıkları. Panel ve CyberOto API ortak kullanır."""
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        if not host_allowed(request):
            return JSONResponse({"detail": "Geçersiz Host"}, status_code=421)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
