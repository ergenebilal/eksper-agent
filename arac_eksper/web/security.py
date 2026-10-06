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
    """Tarayıcıdan gelen değiştirici isteklerde Origin/Referer aynı sunucuyu göstermeli (CSRF ek katmanı)."""
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src:
        return True     # tarayıcı dışı istemci (Bearer ile gelen Jeff vb.)
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
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
                                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
