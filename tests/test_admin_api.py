"""Jeff yönetici API'si: yalnız sunucu içinden + ayrı anahtar; yönetim sayfasının işlemleri JSON olarak; işlem kaydı."""
import pytest
from fastapi.testclient import TestClient

from arac_eksper.config.settings import settings
from arac_eksper.web import accounts, mailer, security, xray_app
from tests.test_xray_api import EXT

ANAHTAR = "j" * 40
H = {"Authorization": "Bearer " + ANAHTAR}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "info@cybergene.co")
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, html=None: sent.append({"to": to, "body": body}))
    return sent


@pytest.fixture
def jeff(monkeypatch, outbox):
    monkeypatch.setattr(settings, "extension_token", EXT)
    monkeypatch.setattr(settings, "admin_api_token", ANAHTAR)
    monkeypatch.setattr(settings, "panel_allowed_hosts", ["127.0.0.1", "panel.test"])
    security._fails.clear()
    with TestClient(xray_app.app, base_url="http://127.0.0.1:8991", client=("127.0.0.1", 50000)) as c:
        yield c


def test_access_only_from_inside_with_its_own_key(jeff, monkeypatch):
    assert jeff.get("/admin-api/v1/saglik", headers=H).status_code == 200
    assert jeff.get("/admin-api/v1/saglik").status_code == 401
    assert jeff.get("/admin-api/v1/saglik", headers={"Authorization": "Bearer " + EXT}).status_code == 401   # eklenti anahtarı geçmez
    assert jeff.get("/admin-api/v1/saglik", headers={**H, "X-Forwarded-For": "1.2.3.4"}).status_code == 404  # vekil üzerinden
    with TestClient(xray_app.app, base_url="http://127.0.0.1:8991", client=("203.0.113.9", 1)) as dis:
        assert dis.get("/admin-api/v1/saglik", headers=H).status_code == 404                                  # dış istemci
    monkeypatch.setattr(settings, "admin_api_token", "kisa")
    assert jeff.get("/admin-api/v1/saglik", headers=H).status_code == 404                                     # yapılandırılmamış


def test_member_lifecycle_is_logged(jeff, outbox):
    r = jeff.post("/admin-api/v1/uyeler", headers=H, json={"email": "Ayse@Ornek.com", "ad": "Ayşe", "gunluk_kota": 12,
                                                         "aylik_kota": 200, "bitis": "2099-01-31", "davet": True})
    assert r.status_code == 201 and r.json()["davet_gonderildi"] is True and outbox[-1]["to"] == "ayse@ornek.com"
    u = r.json()["uye"]
    assert (u["email"], u["gunluk_kota"], u["aylik_kota"], u["bitis"]) == ("ayse@ornek.com", 12, 200, "2099-01-31")
    assert "key_hash" not in str(r.json())
    assert jeff.post("/admin-api/v1/uyeler", headers=H, json={"email": "ayse@ornek.com"}).status_code == 409
    assert jeff.patch("/admin-api/v1/uyeler/ayse@ornek.com", headers=H, json={"gunluk_kota": 3}).json()["uye"]["gunluk_kota"] == 3
    assert jeff.patch(f"/admin-api/v1/uyeler/{u['id']}", headers=H, json={}).status_code == 422
    key = accounts.issue_key(u["id"])
    assert jeff.post("/admin-api/v1/uyeler/ayse@ornek.com/durum", headers=H, json={"durum": "durduruldu"}).json()["uye"]["erisim_sorunu"]
    assert jeff.post("/admin-api/v1/uyeler/ayse@ornek.com/durum", headers=H, json={"durum": "uydurma"}).status_code == 422
    assert jeff.post("/admin-api/v1/uyeler/ayse@ornek.com/cihazlari-kapat", headers=H).json()["kapatilan_anahtar"] == 1
    assert accounts.find_by_key(key) is None
    assert jeff.get("/admin-api/v1/uyeler/yok@ornek.com", headers=H).status_code == 404
    kayit = jeff.get("/admin-api/v1/islem-kaydi", headers=H).json()["kayitlar"]
    assert [k["islem"] for k in kayit][:4] == ["cihazlari_kapat", "uye_durum", "uye_guncelle", "uye_ekle"]
    assert all(k["aktor"] == "jeff-api" for k in kayit)


def test_read_endpoints(jeff):
    mid = accounts.create_member("b@ornek.com", gunluk_kota=5)
    accounts.add_feedback(mid, "1", "ALINIR", 8.0, None, "ekspertiz_temiz", None)
    o = jeff.get("/admin-api/v1/ozet", headers=H).json()
    assert o["uye"]["toplam"] == 1 and o["kalibrasyon"]["sonuclu"] == 1
    assert jeff.get("/admin-api/v1/uyeler", headers=H).json()["uyeler"][0]["email"] == "b@ornek.com"
    d = jeff.get(f"/admin-api/v1/uyeler/{mid}", headers=H).json()
    assert d["uye"]["geri_bildirim"] == 1 and d["geri_bildirim"][0]["sonuc"] == "ekspertiz_temiz"
    assert jeff.get("/admin-api/v1/kalibrasyon", headers=H).json()["tablo"]["ALINIR"]["ekspertiz_temiz"] == 1
    assert "kayitlar" in jeff.get("/admin-api/v1/geri-bildirim", headers=H).json()
    assert "davetler" in jeff.get("/admin-api/v1/davetler", headers=H).json()
