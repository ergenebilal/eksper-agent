"""Panel P0: yetkisiz erişim, CSRF, token zorunluluğu, giriş sınırı, XSS, salt okunur garanti."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from arac_eksper.config.settings import settings
from arac_eksper.schemas import Evidence, MarketStats
from arac_eksper.storage import repo
from arac_eksper.storage.db import Base
from arac_eksper.web import app as webapp, security
from tests.test_hard_fails import _detail, _findings

TOKEN = "t" * 24


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "panel_token", TOKEN)
    security._sessions.clear()
    security._fails.clear()
    webapp.app.dependency_overrides[webapp.get_db] = lambda: db
    with TestClient(webapp.app, base_url="http://panel.test") as c:
        yield c
    webapp.app.dependency_overrides.clear()


def login(c):
    r = c.post("/login", data={"token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    return r


def seed(db, aciklama="Araç temiz. kapora yollayın <script>alert(1)</script>",
         url="https://www.sahibinden.com/ilan/1"):
    from arac_eksper.analysis.rules_engine import determine_verdict
    d = _detail(ilan_no="555", aciklama=aciklama, url=url, fiyat=820000)
    f = _findings(dolandiricilik_sinyalleri=[Evidence(etiket="kapora", alinti="kapora yollayın")])
    mkt = MarketStats(n=20, medyan=900000, p25=880000, p75=920000, guven="yuksek")
    v = determine_verdict(d, f, mkt, max_butce=900000)
    repo.create_or_update_listing(db, d)
    repo.save_verdict(db, v, d, f)
    return d


# ------------------------------------------------------------------ başlatma / yetki
def test_server_refuses_to_start_without_token(monkeypatch):
    for bad in ("", "kisa"):
        monkeypatch.setattr(settings, "panel_token", bad)
        with pytest.raises(RuntimeError):
            with TestClient(webapp.app):
                pass


def test_old_default_token_is_gone():
    from arac_eksper.config.settings import Settings
    assert Settings(_env_file=None).panel_token == ""


def test_unauthenticated_pages_redirect_and_api_is_401(client):
    for path in ("/", "/listings", "/listings/555", "/events", "/system"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    for path in ("/v1/status", "/v1/listings", "/v1/listings/555", "/v1/events"):
        assert client.get(path).status_code == 401, path


def test_healthz_is_public_and_minimal(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_wrong_bearer_and_token_as_cookie_rejected(client):
    assert client.get("/v1/status", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    client.cookies.set("arac_session", TOKEN)       # token'ı çerez olarak sunmak oturum sayılmaz
    assert client.get("/v1/status").status_code == 401


def test_bearer_token_works_for_api(client, db):
    seed(db)
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = client.get("/v1/status", headers=h)
    assert r.status_code == 200 and r.json()["pages_limit"] == settings.max_pages_per_hour
    assert client.get("/v1/listings", headers=h).json()["listings"][0]["ilan_no"] == "555"


def test_session_cookie_flags_and_no_token_in_cookie(client):
    r = login(client)
    c = r.headers["set-cookie"].lower()
    assert "httponly" in c and "samesite=strict" in c and TOKEN not in r.headers["set-cookie"]


def test_login_cross_origin_rejected(client):
    r = client.post("/login", data={"token": TOKEN}, headers={"origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 401


def test_login_rate_limit(client):
    for _ in range(security.LOGIN_MAX_FAILS):
        assert client.post("/login", data={"token": "yanlis"}).status_code == 401
    assert client.post("/login", data={"token": TOKEN}).status_code == 429     # doğru token da artık kilitli


def test_logout_requires_csrf(client):
    login(client)
    assert client.post("/logout", data={"csrf": "yanlis"}, follow_redirects=False).status_code == 403
    assert client.get("/system").status_code == 200           # oturum hâlâ açık
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/").text).group(1)
    r = client.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and client.get("/", follow_redirects=False).status_code == 303


def test_state_changing_api_with_cookie_needs_csrf_header(client):
    login(client)
    from fastapi import HTTPException
    from starlette.requests import Request
    sid = next(iter(security._sessions))
    scope = {"type": "http", "method": "POST", "client": ("1.1.1.1", 1),
             "headers": [(b"cookie", f"arac_session={sid}".encode()), (b"host", b"panel.test")]}
    with pytest.raises(HTTPException) as e:
        security.require_api_auth(Request(scope))
    assert e.value.status_code == 403
    scope["headers"].append((b"x-csrf-token", security._sessions[sid]["csrf"].encode()))
    assert security.require_api_auth(Request(scope)) is None


def test_panel_has_no_write_routes_and_no_extension_api():
    """Panel (HTML ve /v1) salt okunur; yazma yalnız /login ve /logout. Eklenti API'si ayrı uygulamadadır."""
    seen = [r for r in webapp.app.routes if hasattr(r, "path") and hasattr(r, "methods")]
    assert len(seen) > 8, "rota taraması boş kaldı"
    assert all(not r.path.startswith("/api/") for r in seen)
    methods = {m for r in seen if r.path not in ("/login", "/logout") for m in r.methods}
    assert methods <= {"GET", "HEAD"}


# ------------------------------------------------------------------ ekranlar / başlıklar / XSS
def test_screens_render_and_security_headers(client, db):
    seed(db)
    login(client)
    for path in ("/", "/listings", "/listings?etiket=ALINIR&q=meg", "/listings/555", "/events", "/system"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "script-src 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
        assert "cdn." not in r.text and "unpkg" not in r.text and "<script" not in r.text


def test_seller_text_is_escaped_and_quotes_highlighted(client, db):
    seed(db)
    login(client)
    html = client.get("/listings/555").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<mark>kapora yollayın</mark>" in html


def test_javascript_url_is_not_linked(client, db):
    seed(db, url="javascript:alert(1)")
    login(client)
    html = client.get("/listings/555").text
    assert "javascript:" not in html and "sahibinden’de aç" not in html


def test_listing_filter_is_whitelisted(client, db):
    seed(db)
    login(client)
    r = client.get("/listings", params={"etiket": "' OR 1=1 --"})
    assert r.status_code == 200 and "555" in r.text      # geçersiz etiket yok sayılır, SQL'e girmez
    assert client.get("/listings/yok").status_code == 404


def test_api_listing_detail_json(client, db):
    seed(db)
    d = client.get("/v1/listings/555", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert d["verdict"]["etiket"] == "DUSUNULEBILIR" and any(p["vurgulu"] for p in d["aciklama_parcalari"])


def test_token_never_appears_in_pages(client, db):
    seed(db)
    login(client)
    assert all(TOKEN not in client.get(p).text for p in ("/", "/listings", "/listings/555", "/system", "/events"))


def test_panel_does_not_import_collection_code():
    """P0: panel toplama başlatamaz; yalnızca durumu okur."""
    import arac_eksper.web.app as a
    import arac_eksper.web.service as s
    src = open(a.__file__, encoding="utf-8").read() + open(s.__file__, encoding="utf-8").read()
    assert "PlaywrightCollector" not in src and "run_search" not in src and "run_watch" not in src
