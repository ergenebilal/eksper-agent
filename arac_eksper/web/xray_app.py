"""otoXray AI API'sinin ayrı uygulaması: yalnızca /api/v1 + /healthz. Panel, toplayıcı (collector), veritabanı ve
zamanlayıcı kodlarını İÇE AKTARMAZ (testle denetlenir): sunucu tarafında ilan sayfası çeken hiçbir kod yoktur."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from arac_eksper.config.settings import settings
from arac_eksper.web import api, security


@asynccontextmanager
async def lifespan(app: FastAPI):
    problem = security.extension_problem()
    if problem:
        raise RuntimeError(problem)      # token yoksa/zayıfsa sunucu ayağa kalkmaz
    yield


app = FastAPI(title="otoXray AI API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
security.harden(app)
app.include_router(api.router)


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def serve() -> None:
    import sys
    import uvicorn
    problem = security.extension_problem()
    if problem:
        print(problem + " .env dosyasına EXTENSION_TOKEN=<en az 16 rastgele karakter> ekleyin.", file=sys.stderr)
        raise SystemExit(3)
    if settings.xray_host not in ("127.0.0.1", "localhost", "::1"):
        print(f"UYARI: API {settings.xray_host} adresinde dinliyor. Yalnızca yerel ağ/Tailscale için; internete açmayın.",
              file=sys.stderr)
    # access_log kapalı: istek yolları bile kaydedilmez
    uvicorn.run("arac_eksper.web.xray_app:app", host=settings.xray_host, port=settings.xray_port,
                log_level="warning", access_log=False)
