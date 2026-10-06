"""Tek-toplama kilidi: aynı anda yalnızca bir toplama işi çalışır (rate limiter'ı paralel işlerle aşmayı önler).
Platformdan bağımsız: O_EXCL ile oluşturulan kilit dosyası, bayatsa (çökmüş süreç) devralınır."""
import os
import time
from contextlib import contextmanager
from pathlib import Path
from arac_eksper.config.settings import DATA_DIR, settings

LOCK_PATH = DATA_DIR / "collect.lock"


class CollectionBusy(Exception):
    pass


@contextmanager
def collection_lock(path: Path | None = None):
    path = path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > settings.lock_stale_minutes * 60:
        path.unlink(missing_ok=True)  # bayat kilit
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise CollectionBusy("Başka bir toplama işi çalışıyor.")
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
