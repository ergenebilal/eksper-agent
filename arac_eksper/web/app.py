import os
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arac_eksper.config.settings import settings
from arac_eksper.storage.db import SessionLocal
from arac_eksper.storage import repo

# Templates setup
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(title="Araç Eksper Panel", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Dependency for DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Auth Dependency
def verify_auth(request: Request):
    token = request.cookies.get("panel_token")
    if not token or token != settings.panel_token:
        # Check authorization header for API requests
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {settings.panel_token}":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

def require_html_auth(request: Request):
    token = request.cookies.get("panel_token")
    if not token or token != settings.panel_token:
        # Redirect to login
        raise HTTPException(status_code=302, headers={"Location": "/login"})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    token = form.get("token")
    if token == settings.panel_token:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="panel_token", value=token, httponly=True, max_age=86400 * 30)
        return response
    return templates.TemplateResponse(request, "login.html", {"error": "Hatalı token"})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("panel_token")
    return response

# P0 Routes - Read Only

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_html_auth)])
async def dashboard(request: Request, db=Depends(get_db)):
    from arac_eksper.collector import guard
    from arac_eksper.storage.models import FetchLog, Watch, Verdict
    from datetime import datetime, timezone, timedelta
    
    # 1. Son başarılı çekim
    last_ok = db.query(FetchLog).filter(FetchLog.status == "OK").order_by(FetchLog.id.desc()).first()
    
    # 2. Sayfa kullanımı (son 1 saat)
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    pages_used = db.query(FetchLog).filter(FetchLog.timestamp >= hour_ago).count()
    
    # 3. Engel durumu
    blocked_until = guard.is_blocked_now(db)
    
    # 4. Son 24 saat 🟢/🟡/🔴
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    verdicts = db.query(Verdict).filter(Verdict.created_at >= day_ago).all()
    v_stats = {"alinir": 0, "dusunulebilir": 0, "alinmaz": 0, "beklemede": 0}
    for v in verdicts:
        if v.beklemede:
            v_stats["beklemede"] += 1
        elif v.etiket == "ALINIR":
            v_stats["alinir"] += 1
        elif v.etiket == "DUSUNULEBILIR":
            v_stats["dusunulebilir"] += 1
        else:
            v_stats["alinmaz"] += 1
            
    # 5. Radarlar
    watches = db.query(Watch).all()
    
    return templates.TemplateResponse(request, "dashboard.html", {
        "last_ok": last_ok,
        "pages_used": pages_used,
        "max_pages": settings.max_pages_per_hour,
        "blocked_until": blocked_until,
        "v_stats": v_stats,
        "watches": watches,
    })

@app.get("/listings", response_class=HTMLResponse, dependencies=[Depends(require_html_auth)])
async def listings_page(request: Request, db=Depends(get_db)):
    from arac_eksper.storage.models import Verdict
    from sqlalchemy.orm import joinedload
    
    # Tüm karne kararlarını (ve ilişkili ilanları) çek, en yüksek puandan en düşüğe, sonra tarihe göre sırala
    verdicts = (
        db.query(Verdict)
        .options(joinedload(Verdict.listing))
        .order_by(
            # Kendi içinde etiket sırası: ALINIR (1), DUSUNULEBILIR (2), ALINMAZ (3)
            # SQLAlchemy'de case kullanmak yerine basitçe skora göre dizebiliriz:
            Verdict.guven_skoru.desc(),
            Verdict.created_at.desc()
        )
        .limit(100)
        .all()
    )
    
    return templates.TemplateResponse(request, "listings.html", {
        "verdicts": verdicts
    })

@app.get("/search", response_class=HTMLResponse, dependencies=[Depends(require_html_auth)])
async def search_page(request: Request):
    return templates.TemplateResponse(request, "search.html", {})

# Run with: uv run uvicorn arac_eksper.web.app:app --reload --port 8990
