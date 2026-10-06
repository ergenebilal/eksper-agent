from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from arac_eksper.config.settings import settings

def _ensure_sqlite_dir(url: str) -> None:
    u = make_url(url)
    if u.drivername.startswith("sqlite") and u.database and u.database != ":memory:":
        Path(u.database).parent.mkdir(parents=True, exist_ok=True)

_ensure_sqlite_dir(settings.database_url)

engine = create_engine(
    settings.database_url, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
