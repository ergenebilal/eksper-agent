"""otoXray davetli kullanıcıları: kişi başı erişim anahtarı, günlük kota sayacı, kullanıcının kendi gönderdiği geri bildirim.

İLAN İÇERİĞİ SAKLANMAZ (açıklama, başlık, fiyat, parça tablosu yok). Saklananlar: anahtarın SHA-256 özeti (anahtarın
kendisi değil), gün başına sayaçlar ve kullanıcının bilerek gönderdiği geri bildirim (ilan no, gördüğü etiket, oy,
ekspertiz sonucu, telefonları maskelenmiş kısa not). Stdlib sqlite3 kullanır: API süreci SQLAlchemy yüklemez.
"""
import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from arac_eksper.config.settings import PROJECT_ROOT, settings

KEY_PREFIX = "oxr_"
SONUCLAR = ("ekspertiz_temiz", "ekspertiz_kucuk_kusur", "ekspertiz_agir_kusur", "gitmedim")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, ad TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, key_prefix TEXT NOT NULL,
    gunluk_kota INTEGER NOT NULL, aktif INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER NOT NULL, gun TEXT NOT NULL, tur TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, gun, tur));
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, ilan_no TEXT NOT NULL,
    etiket TEXT, skor REAL, oy TEXT, sonuc TEXT, notu TEXT);
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


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ------------------------------------------------------------------ kullanıcılar
def create_user(ad: str, gunluk_kota: int | None = None) -> tuple[int, str]:
    """Yeni anahtar üretir; anahtar YALNIZ burada döner, sonra geri alınamaz (yalnız özeti saklanır)."""
    key = KEY_PREFIX + secrets.token_urlsafe(24)
    kota = settings.user_daily_quota if gunluk_kota is None else gunluk_kota
    with closing(_conn()) as c, c:
        cur = c.execute("INSERT INTO users (ad, key_hash, key_prefix, gunluk_kota, created_at) VALUES (?,?,?,?,?)",
                        (ad.strip()[:60], hash_key(key), key[:10], kota, _now()))
        return cur.lastrowid, key


def find_by_key(key: str) -> dict | None:
    if not key.startswith(KEY_PREFIX):
        return None
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM users WHERE key_hash = ? AND aktif = 1", (hash_key(key),)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute("""SELECT u.id, u.ad, u.key_prefix, u.gunluk_kota, u.aktif, u.created_at,
            COALESCE((SELECT n FROM usage WHERE user_id = u.id AND gun = ? AND tur = 'analyze'), 0) AS bugun,
            COALESCE((SELECT SUM(n) FROM usage WHERE user_id = u.id AND tur = 'analyze'), 0) AS toplam,
            (SELECT COUNT(*) FROM feedback WHERE user_id = u.id) AS geri_bildirim
            FROM users u ORDER BY u.id""", (_today(),)).fetchall()
    return [dict(r) for r in rows]


def revoke(user_id: int) -> bool:
    with closing(_conn()) as c, c:
        return c.execute("UPDATE users SET aktif = 0, revoked_at = ? WHERE id = ? AND aktif = 1",
                         (_now(), user_id)).rowcount == 1


def set_quota(user_id: int, kota: int) -> bool:
    with closing(_conn()) as c, c:
        return c.execute("UPDATE users SET gunluk_kota = ? WHERE id = ?", (kota, user_id)).rowcount == 1


# ------------------------------------------------------------------ kota
def used_today(user_id: int, tur: str = "analyze") -> int:
    with closing(_conn()) as c:
        row = c.execute("SELECT n FROM usage WHERE user_id = ? AND gun = ? AND tur = ?",
                        (user_id, _today(), tur)).fetchone()
    return row["n"] if row else 0


def consume(user_id: int, limit: int | None, tur: str = "analyze") -> bool:
    """Atomik: sınır doluysa False (sayaç artmaz). limit None = yalnız say."""
    with closing(_conn()) as c, c:
        c.execute("INSERT OR IGNORE INTO usage (user_id, gun, tur, n) VALUES (?,?,?,0)", (user_id, _today(), tur))
        q = "UPDATE usage SET n = n + 1 WHERE user_id = ? AND gun = ? AND tur = ?"
        args: tuple = (user_id, _today(), tur)
        if limit is not None:
            q += " AND n < ?"
            args += (limit,)
        return c.execute(q, args).rowcount == 1


def refund(user_id: int, tur: str = "analyze") -> None:
    with closing(_conn()) as c, c:
        c.execute("UPDATE usage SET n = MAX(n - 1, 0) WHERE user_id = ? AND gun = ? AND tur = ?",
                  (user_id, _today(), tur))


# ------------------------------------------------------------------ geri bildirim
def add_feedback(user_id: int, ilan_no: str, etiket: str | None, skor: float | None, oy: str | None,
                 sonuc: str | None, notu: str | None) -> int:
    with closing(_conn()) as c, c:
        return c.execute("INSERT INTO feedback (user_id, created_at, ilan_no, etiket, skor, oy, sonuc, notu) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (user_id, _now(), ilan_no, etiket, skor, oy, sonuc, notu)).lastrowid


def list_feedback(limit: int = 200) -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute("""SELECT f.*, u.ad FROM feedback f LEFT JOIN users u ON u.id = f.user_id
                            ORDER BY f.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]
