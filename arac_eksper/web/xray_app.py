"""CyberOto AI API'sinin ayrı uygulaması: yalnızca /api/v1 + /healthz. Panel, toplayıcı (collector), veritabanı ve
zamanlayıcı kodlarını İÇE AKTARMAZ (testle denetlenir): sunucu tarafında ilan sayfası çeken hiçbir kod yoktur."""
import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, api, security, yonetim


@asynccontextmanager
async def lifespan(app: FastAPI):
    problem = security.extension_problem()
    if problem:
        raise RuntimeError(problem)      # token yoksa/zayıfsa sunucu ayağa kalkmaz

    async def temizlik():                # saklama süresi dolan teknik kayıtlar: açılıştan 1 dk sonra ve günde bir
        while True:
            await asyncio.sleep(60)
            if accounts._path().exists():   # sahip anahtarıyla çalışan kurulumda hesap deposu hiç oluşturulmaz
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(accounts.prune)
            await asyncio.sleep(86400 - 60)

    task = asyncio.create_task(temizlik())
    yield
    task.cancel()


app = FastAPI(title="CyberOto AI API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
security.harden(app)
app.include_router(api.router)
app.include_router(api.auth_router)
app.include_router(yonetim.router)


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _fail_if_port_busy() -> None:
    """Port doluysa ham 'Errno 10048' yerine ne olduğunu söyle (çoğu zaman sunucu zaten çalışıyordur)."""
    import socket
    import sys
    import urllib.request
    with socket.socket() as s:
        if s.connect_ex((settings.xray_host, settings.xray_port)) != 0:
            return
    url = f"http://{settings.xray_host}:{settings.xray_port}/healthz"
    try:
        ok = b'"ok":true' in urllib.request.urlopen(url, timeout=2).read()
    except Exception:  # noqa: BLE001
        ok = False
    if ok:
        print(f"CyberOto sunucusu ZATEN çalışıyor ({url} sağlıklı). Yeniden başlatmak için çalıştığı pencerede Ctrl+C "
              "yapın ya da otoxray-yeniden-baslat.cmd dosyasını çalıştırın.", file=sys.stderr)
    else:
        print(f"{settings.xray_port} portu başka bir program tarafından kullanılıyor (CyberOto değil). "
              "XRAY_PORT ile başka bir port seçin.", file=sys.stderr)
    raise SystemExit(4)


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
    _fail_if_port_busy()
    # access_log kapalı: istek yolları bile kaydedilmez
    # Ters vekil (Caddy) arkasında gerçek istemci IP'si yalnız güvenilen vekilden alınır (deneme sınırı kişiye özel kalsın)
    uvicorn.run("arac_eksper.web.xray_app:app", host=settings.xray_host, port=settings.xray_port,
                log_level="warning", access_log=False, proxy_headers=True,
                forwarded_allow_ips=settings.xray_forwarded_allow_ips)
