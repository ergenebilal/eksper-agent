"""Araç Eksper paneli (P0: salt okunur). Yerel öncelikli; token olmadan BAŞLAMAZ.
HTML ekranları ve /v1 JSON uç noktaları aynı veri katmanını (service.py) kullanır.
Panel hiçbir toplama işi başlatmaz, hiçbir koruma ayarını değiştirmez (P0'da yazma yolu yok)."""
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arac_eksper.config.settings import settings
from arac_eksper.storage.db import SessionLocal
from arac_eksper.web import security, service

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))   # .html için otomatik kaçış AÇIK


@asynccontextmanager
async def lifespan(app: FastAPI):
    security.check_startup()     # token yoksa/zayıfsa sunucu ayağa kalkmaz
    yield


app = FastAPI(title="Araç Eksper Panel", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in security.SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def page(request: Request, name: str, sess: dict, **ctx):
    return templates.TemplateResponse(request, name, {"csrf": sess["csrf"], **ctx})


# ------------------------------------------------------------------ giriş / çıkış
@app.get("/healthz")
async def healthz():
    return {"ok": True}      # yalnızca bu; sürüm/yol/ayar bilgisi yok


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, token: str = Form("")):
    ip = security.client_ip(request)
    if security.login_blocked(ip):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Çok fazla deneme. Biraz sonra tekrar deneyin."}, status_code=429)
    if not security.origin_ok(request) or not security.token_matches(token):
        security.record_fail(ip)
        return templates.TemplateResponse(request, "login.html", {"error": "Giriş başarısız."}, status_code=401)
    sid, _ = security.new_session()
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(security.COOKIE, sid, httponly=True, samesite="strict", secure=settings.panel_cookie_secure,
                    max_age=settings.panel_session_hours * 3600, path="/")
    return resp


@app.post("/logout")
async def logout(request: Request, csrf: str = Form(""), sess: dict = Depends(security.require_page_auth)):
    if not security.origin_ok(request) or not hmac.compare_digest(csrf, sess["csrf"]):
        raise HTTPException(status_code=403, detail="CSRF doğrulaması başarısız")
    security.drop_session(request)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(security.COOKIE, path="/")
    return resp


# ------------------------------------------------------------------ ekranlar (P0, salt okunur)
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db=Depends(get_db), sess=Depends(security.require_page_auth)):
    return page(request, "dashboard.html", sess, s=service.status(db), nav="home")


@app.get("/listings", response_class=HTMLResponse)
async def listings_page(request: Request, etiket: str | None = Query(None, max_length=20),
                        q: str | None = Query(None, max_length=60), db=Depends(get_db),
                        sess=Depends(security.require_page_auth)):
    return page(request, "listings.html", sess, rows=service.listings(db, etiket, q), etiket=etiket, q=q or "",
                nav="listings")


@app.get("/listings/{ilan_no}", response_class=HTMLResponse)
async def listing_page(request: Request, ilan_no: str, db=Depends(get_db), sess=Depends(security.require_page_auth)):
    d = service.listing_detail(db, ilan_no[:40])
    if not d:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    return page(request, "detail.html", sess, d=d, nav="listings")


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, db=Depends(get_db), sess=Depends(security.require_page_auth)):
    return page(request, "events.html", sess, rows=service.events(db), nav="events")


@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, db=Depends(get_db), sess=Depends(security.require_page_auth)):
    return page(request, "system.html", sess, s=service.system(db), nav="system")


# ------------------------------------------------------------------ /v1 (Jeff + panel, aynı veri)
@app.get("/v1/status", dependencies=[Depends(security.require_api_auth)])
async def v1_status(db=Depends(get_db)):
    return service.status(db)


@app.get("/v1/listings", dependencies=[Depends(security.require_api_auth)])
async def v1_listings(etiket: str | None = Query(None, max_length=20), q: str | None = Query(None, max_length=60),
                      limit: int = Query(100, ge=1, le=service.MAX_LIST), db=Depends(get_db)):
    return {"listings": service.listings(db, etiket, q, limit)}


@app.get("/v1/listings/{ilan_no}", dependencies=[Depends(security.require_api_auth)])
async def v1_listing(ilan_no: str, db=Depends(get_db)):
    d = service.listing_detail(db, ilan_no[:40])
    if not d:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    d["aciklama_parcalari"] = [{"metin": t, "vurgulu": h} for t, h in d["aciklama_parcalari"]]
    return d


@app.get("/v1/events", dependencies=[Depends(security.require_api_auth)])
async def v1_events(since: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=service.MAX_LIST), db=Depends(get_db)):
    return {"events": service.events(db, since, limit)}


def serve() -> None:
    """`arac panel serve`: token yoksa başlamaz; yerel olmayan bind uyarı verir."""
    import sys
    import uvicorn
    problem = security.token_problem()
    if problem:
        print(problem + " .env dosyasına PANEL_TOKEN=<en az 16 rastgele karakter> ekleyin.", file=sys.stderr)
        raise SystemExit(3)
    if settings.panel_host not in ("127.0.0.1", "localhost", "::1"):
        print(f"UYARI: panel {settings.panel_host} adresinde dinliyor. Yalnızca Tailscale/yerel ağ için; "
              "internete açmayın.", file=sys.stderr)
    uvicorn.run("arac_eksper.web.app:app", host=settings.panel_host, port=settings.panel_port, log_level="warning")
