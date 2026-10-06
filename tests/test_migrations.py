"""`arac db init` (alembic) ile kurulan şema, modellerin beklediği tüm kolonları içermeli.
Diğer testler create_all kullandığı için bu açığı yakalayamıyordu."""
from pathlib import Path
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from arac_eksper.config.settings import settings
from arac_eksper.storage.models import Base

ROOT = Path(__file__).resolve().parent.parent

def test_alembic_head_matches_models(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")

    insp = sa.inspect(sa.create_engine(url))
    for table in Base.metadata.sorted_tables:
        assert table.name in insp.get_table_names(), f"tablo yok: {table.name}"
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        model_cols = {c.name for c in table.columns}
        assert model_cols <= db_cols, f"{table.name}: migration'da eksik kolonlar {model_cols - db_cols}"

def test_migration_is_idempotent_on_create_all_db(tmp_path, monkeypatch):
    """create_all ile kurulmuş DB'ye (örn. live_validation.py) head uygulanınca çökmemeli."""
    url = f"sqlite:///{tmp_path / 'c.db'}"
    Base.metadata.create_all(sa.create_engine(url))
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    # create_all DB'sinde alembic_version yok: önce başlangıç noktasını damgala, sonra yükselt
    command.stamp(cfg, "be521097f002")
    command.upgrade(cfg, "head")
