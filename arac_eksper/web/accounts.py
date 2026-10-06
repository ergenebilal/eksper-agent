"""otoXray davetli üyeleri: e-postaya bağlı hesap + kişiye özel haklar, e-posta koduyla giriş, cihaz anahtarları,
günlük/aylık sayaçlar, kullanıcının bilerek gönderdiği geri bildirim ve yönetim oturumları.

İLAN İÇERİĞİ SAKLANMAZ (açıklama, başlık, fiyat, parça tablosu yok). Anahtar, giriş kodu ve oturum kimliği yalnızca
SHA-256 özetiyle saklanır. Kişisel veri olarak yalnızca e-posta ve (isteğe bağlı) ad tutulur. Stdlib sqlite3 kullanılır:
API süreci SQLAlchemy yüklemez.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from arac_eksper.config.settings import PROJECT_ROOT, settings

KEY_PREFIX = "oxr_"
SONUCLAR = ("ekspertiz_temiz", "ekspertiz_kucuk_kusur", "ekspertiz_agir_kusur", "gitmedim")
DURUMLAR = ("aktif", "durduruldu", "iptal")
CODE_TTL_S, CODE_MAX_ATTEMPTS = 10 * 60, 5
CODE_MIN_GAP_S, CODE_MAX_PER_HOUR = 60, 5
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, ad TEXT, durum TEXT NOT NULL DEFAULT 'aktif',
    gunluk_kota INTEGER NOT NULL, aylik_kota INTEGER, bitis TEXT, rozet INTEGER NOT NULL DEFAULT 1, notu TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, son_kullanim TEXT);
CREATE TABLE IF NOT EXISTS member_keys (
    id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL, key_hash TEXT NOT NULL UNIQUE, key_prefix TEXT NOT NULL,
    cihaz TEXT, created_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS login_codes (
    email TEXT NOT NULL, amac TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (email, amac));
CREATE TABLE IF NOT EXISTS code_sends (email TEXT NOT NULL, amac TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
    member_id INTEGER NOT NULL, gun TEXT NOT NULL, tur TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (member_id, gun, tur));
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL, created_at TEXT NOT NULL, ilan_no TEXT NOT NULL,
    etiket TEXT, skor REAL, oy TEXT, sonuc TEXT, notu TEXT);
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL, sent_at TEXT NOT NULL, ok INTEGER NOT NULL, hata TEXT);
CREATE TABLE IF NOT EXISTS admin_sessions (
    sid_hash TEXT PRIMARY KEY, email TEXT NOT NULL, csrf TEXT NOT NULL, expires_at REAL NOT NULL);
"""


def _path() -> Path:
    p = Path(settings.xray_accounts_db)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _conn() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(_SCHEMA)
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


hash_key = _sha


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e):
        raise ValueError("Geçersiz e-posta adresi")
    return e


# ------------------------------------------------------------------ üyeler
_FIELDS = ("ad", "gunluk_kota", "aylik_kota", "bitis", "rozet", "notu")


def _check(f: dict) -> dict:
    out = {}
    if "ad" in f:
        out["ad"] = (f["ad"] or "").strip()[:60] or None
    if "gunluk_kota" in f:
        if f["gunluk_kota"] is None or not 0 <= int(f["gunluk_kota"]) <= 10_000:
            raise ValueError("Günlük hak 0-10000 arası olmalı")
        out["gunluk_kota"] = int(f["gunluk_kota"])
    if "aylik_kota" in f:
        v = f["aylik_kota"]
        if v not in (None, "") and not 0 <= int(v) <= 300_000:
            raise ValueError("Aylık hak 0-300000 arası olmalı")
        out["aylik_kota"] = None if v in (None, "") else int(v)
    if "bitis" in f:
        v = f["bitis"]
        out["bitis"] = None if v in (None, "") else date.fromisoformat(str(v)).isoformat()
    if "rozet" in f:
        out["rozet"] = 1 if f["rozet"] else 0
    if "notu" in f:
        out["notu"] = (f["notu"] or "").strip()[:300] or None
    return out


def create_member(email: str, ad: str | None = None, gunluk_kota: int | None = None, aylik_kota: int | None = None,
                  bitis: str | None = None, rozet: bool = True, notu: str | None = None) -> int:
    e = normalize_email(email)
    f = _check({"ad": ad, "gunluk_kota": settings.user_daily_quota if gunluk_kota is None else gunluk_kota,
                "aylik_kota": aylik_kota, "bitis": bitis, "rozet": rozet, "notu": notu})
    with closing(_conn()) as c, c:
        if c.execute("SELECT 1 FROM members WHERE email = ?", (e,)).fetchone():
            raise ValueError("Bu e-posta zaten kayıtlı")
        return c.execute("INSERT INTO members (email, ad, gunluk_kota, aylik_kota, bitis, rozet, notu, created_at, "
                         "updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (e, f["ad"], f["gunluk_kota"], f["aylik_kota"], f["bitis"], f["rozet"], f["notu"],
                          _now(), _now())).lastrowid


def update_member(member_id: int, **fields) -> bool:
    f = _check({k: v for k, v in fields.items() if k in _FIELDS})
    if not f:
        return False
    sets = ", ".join(f"{k} = ?" for k in f)
    with closing(_conn()) as c, c:
        return c.execute(f"UPDATE members SET {sets}, updated_at = ? WHERE id = ?",
                         (*f.values(), _now(), member_id)).rowcount == 1


def set_status(member_id: int, durum: str) -> bool:
    if durum not in DURUMLAR:
        raise ValueError("Geçersiz durum")
    with closing(_conn()) as c, c:
        ok = c.execute("UPDATE members SET durum = ?, updated_at = ? WHERE id = ?",
                       (durum, _now(), member_id)).rowcount == 1
        if ok and durum == "iptal":        # iptal: tüm cihaz anahtarları da kalıcı olarak düşer
            c.execute("UPDATE member_keys SET revoked_at = ? WHERE member_id = ? AND revoked_at IS NULL",
                      (_now(), member_id))
        return ok


def get_member(member_id: int) -> dict | None:
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    return dict(row) if row else None


def get_member_by_email(email: str) -> dict | None:
    try:
        e = normalize_email(email)
    except ValueError:
        return None
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM members WHERE email = ?", (e,)).fetchone()
    return dict(row) if row else None


def access_problem(m: dict) -> str | None:
    """Üyenin şu an analiz yapmasını engelleyen durum (yoksa None)."""
    if m["durum"] != "aktif":
        return "Erişiminiz durduruldu." if m["durum"] == "durduruldu" else "Erişiminiz kapatıldı."
    if m.get("bitis") and m["bitis"] < _today():
        return f"Erişim süreniz {m['bitis']} tarihinde doldu."
    return None


def list_members() -> list[dict]:
    month = _today()[:7] + "%"
    with closing(_conn()) as c:
        rows = c.execute("""SELECT m.*,
            COALESCE((SELECT n FROM usage WHERE member_id = m.id AND gun = ? AND tur = 'analyze'), 0) AS bugun,
            COALESCE((SELECT SUM(n) FROM usage WHERE member_id = m.id AND gun LIKE ? AND tur = 'analyze'), 0) AS bu_ay,
            COALESCE((SELECT SUM(n) FROM usage WHERE member_id = m.id AND tur = 'analyze'), 0) AS toplam,
            (SELECT COUNT(*) FROM member_keys WHERE member_id = m.id AND revoked_at IS NULL) AS cihaz,
            (SELECT COUNT(*) FROM feedback WHERE member_id = m.id) AS geri_bildirim
            FROM members m ORDER BY m.id""", (_today(), month)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ cihaz anahtarları
def issue_key(member_id: int, cihaz: str | None = None) -> str:
    """Yeni cihaz anahtarı; YALNIZ burada döner, sunucuda yalnızca özeti kalır."""
    key = KEY_PREFIX + secrets.token_urlsafe(24)
    with closing(_conn()) as c, c:
        c.execute("INSERT INTO member_keys (member_id, key_hash, key_prefix, cihaz, created_at) VALUES (?,?,?,?,?)",
                  (member_id, _sha(key), key[:10], (cihaz or "")[:60] or None, _now()))
    return key


def find_by_key(key: str) -> dict | None:
    """Geçerli (iptal edilmemiş) anahtarın üyesi; üye durdurulmuş/süresi dolmuş olabilir → access_problem."""
    if not key.startswith(KEY_PREFIX):
        return None
    with closing(_conn()) as c, c:
        row = c.execute("""SELECT m.*, k.id AS key_id FROM member_keys k JOIN members m ON m.id = k.member_id
                           WHERE k.key_hash = ? AND k.revoked_at IS NULL AND m.durum != 'iptal'""",
                        (_sha(key),)).fetchone()
        if row:
            c.execute("UPDATE members SET son_kullanim = ? WHERE id = ?", (_now(), row["id"]))
    return dict(row) if row else None


def revoke_key(key_id: int) -> bool:
    with closing(_conn()) as c, c:
        return c.execute("UPDATE member_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                         (_now(), key_id)).rowcount == 1


def revoke_all_keys(member_id: int) -> int:
    with closing(_conn()) as c, c:
        return c.execute("UPDATE member_keys SET revoked_at = ? WHERE member_id = ? AND revoked_at IS NULL",
                         (_now(), member_id)).rowcount


# ------------------------------------------------------------------ e-posta kodları
def _code_hash(email: str, amac: str, code: str) -> str:
    return _sha(f"{amac}:{email}:{code}")


def create_code(email: str, amac: str) -> str | None:
    """Tek kullanımlık 6 haneli kod. Aynı adrese 60 sn'de birden, saatte 5'ten fazla kod üretilmez (None)."""
    e = normalize_email(email)
    now = time.time()
    with closing(_conn()) as c, c:
        c.execute("DELETE FROM code_sends WHERE ts < ?", (now - 3600,))
        sends = [r["ts"] for r in c.execute("SELECT ts FROM code_sends WHERE email = ? AND amac = ?", (e, amac))]
        if len(sends) >= CODE_MAX_PER_HOUR or (sends and now - max(sends) < CODE_MIN_GAP_S):
            return None
        code = f"{secrets.randbelow(10**6):06d}"
        c.execute("INSERT OR REPLACE INTO login_codes (email, amac, code_hash, expires_at, attempts) VALUES (?,?,?,?,0)",
                  (e, amac, _code_hash(e, amac, code), now + CODE_TTL_S))
        c.execute("INSERT INTO code_sends (email, amac, ts) VALUES (?,?,?)", (e, amac, now))
    return code


def verify_code(email: str, amac: str, code: str) -> bool:
    """Doğruysa kodu tüketir. Süresi dolmuş ya da 5 kez yanlış girilmiş kod geçersizdir."""
    try:
        e = normalize_email(email)
    except ValueError:
        return False
    code = (code or "").strip()
    with closing(_conn()) as c, c:
        row = c.execute("SELECT * FROM login_codes WHERE email = ? AND amac = ?", (e, amac)).fetchone()
        if not row or row["expires_at"] < time.time() or row["attempts"] >= CODE_MAX_ATTEMPTS:
            return False
        if not (code.isdigit() and hmac.compare_digest(row["code_hash"], _code_hash(e, amac, code))):
            c.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE email = ? AND amac = ?", (e, amac))
            return False
        c.execute("DELETE FROM login_codes WHERE email = ? AND amac = ?", (e, amac))
        return True


# ------------------------------------------------------------------ kota
def used_today(member_id: int, tur: str = "analyze") -> int:
    with closing(_conn()) as c:
        row = c.execute("SELECT n FROM usage WHERE member_id = ? AND gun = ? AND tur = ?",
                        (member_id, _today(), tur)).fetchone()
    return row["n"] if row else 0


def used_month(member_id: int, tur: str = "analyze") -> int:
    with closing(_conn()) as c:
        row = c.execute("SELECT COALESCE(SUM(n), 0) AS n FROM usage WHERE member_id = ? AND gun LIKE ? AND tur = ?",
                        (member_id, _today()[:7] + "%", tur)).fetchone()
    return row["n"]


def consume(member_id: int, limit: int | None, tur: str = "analyze", monthly: int | None = None) -> bool:
    """Atomik: günlük (ve verildiyse aylık) sınır doluysa False, sayaç artmaz. limit None = yalnız say."""
    with closing(_conn()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        if monthly is not None:
            n = c.execute("SELECT COALESCE(SUM(n), 0) FROM usage WHERE member_id = ? AND gun LIKE ? AND tur = ?",
                          (member_id, _today()[:7] + "%", tur)).fetchone()[0]
            if n >= monthly:
                return False
        c.execute("INSERT OR IGNORE INTO usage (member_id, gun, tur, n) VALUES (?,?,?,0)", (member_id, _today(), tur))
        q = "UPDATE usage SET n = n + 1 WHERE member_id = ? AND gun = ? AND tur = ?"
        args: tuple = (member_id, _today(), tur)
        if limit is not None:
            q += " AND n < ?"
            args += (limit,)
        return c.execute(q, args).rowcount == 1


def refund(member_id: int, tur: str = "analyze") -> None:
    with closing(_conn()) as c, c:
        c.execute("UPDATE usage SET n = MAX(n - 1, 0) WHERE member_id = ? AND gun = ? AND tur = ?",
                  (member_id, _today(), tur))


# ------------------------------------------------------------------ geri bildirim
def add_feedback(member_id: int, ilan_no: str, etiket: str | None, skor: float | None, oy: str | None,
                 sonuc: str | None, notu: str | None) -> int:
    with closing(_conn()) as c, c:
        return c.execute("INSERT INTO feedback (member_id, created_at, ilan_no, etiket, skor, oy, sonuc, notu) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (member_id, _now(), ilan_no, etiket, skor, oy, sonuc, notu)).lastrowid


def list_feedback(limit: int = 200) -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute("""SELECT f.*, m.email, m.ad FROM feedback f LEFT JOIN members m ON m.id = f.member_id
                            ORDER BY f.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ yönetim oturumları
def new_admin_session(email: str, hours: int = 12) -> tuple[str, str]:
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with closing(_conn()) as c, c:
        c.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (time.time(),))
        c.execute("INSERT INTO admin_sessions (sid_hash, email, csrf, expires_at) VALUES (?,?,?,?)",
                  (_sha(sid), email, csrf, time.time() + hours * 3600))
    return sid, csrf


def get_admin_session(sid: str | None) -> dict | None:
    if not sid:
        return None
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM admin_sessions WHERE sid_hash = ? AND expires_at > ?",
                        (_sha(sid), time.time())).fetchone()
    return dict(row) if row else None


def drop_admin_session(sid: str | None) -> None:
    if sid:
        with closing(_conn()) as c, c:
            c.execute("DELETE FROM admin_sessions WHERE sid_hash = ?", (_sha(sid),))


# ------------------------------------------------------------------ davetler
def record_invite(member_id: int, ok: bool, hata: str | None = None) -> None:
    """Davet e-postası denemesi: yalnız sonuç ve hata TÜRÜ (adres/içerik yok)."""
    with closing(_conn()) as c, c:
        c.execute("INSERT INTO invites (member_id, sent_at, ok, hata) VALUES (?,?,?,?)",
                  (member_id, _now(), 1 if ok else 0, (hata or "")[:120] or None))


def list_invites() -> list[dict]:
    """Davet gönderilmiş (denenmiş) üyeler: son deneme, deneme sayısı, ilk giriş (katılım)."""
    with closing(_conn()) as c:
        rows = c.execute("""SELECT m.id, m.email, m.ad, m.durum, m.bitis, m.gunluk_kota,
            i.sent_at AS son_davet, i.ok AS son_ok, i.hata AS son_hata,
            (SELECT COUNT(*) FROM invites WHERE member_id = m.id) AS deneme,
            (SELECT MIN(created_at) FROM member_keys WHERE member_id = m.id) AS ilk_giris
            FROM members m JOIN invites i ON i.id = (SELECT MAX(id) FROM invites WHERE member_id = m.id)
            ORDER BY i.id DESC""").fetchall()
    return [dict(r) for r in rows]
