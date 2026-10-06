from arac_eksper.storage.db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
