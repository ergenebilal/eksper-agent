"""Phase 3: listings.marka/model/source, verdict kolonları, events tablosu

Not: 6df48b8f9350 migration'ı boştu (pass); bu yüzden `arac db init` ile kurulan
veritabanlarında listings.marka/model/source yoktu. Bu migration idempotenttir:
create_all ile oluşmuş veritabanlarında zaten var olan kolonları atlar.

Revision ID: c3a91f27d5e0
Revises: be521097f002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3a91f27d5e0"
down_revision: Union[str, Sequence[str], None] = "be521097f002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _cols(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add("listings", sa.Column("marka", sa.String(), nullable=False, server_default=""))
    _add("listings", sa.Column("model", sa.String(), nullable=False, server_default=""))
    _add("listings", sa.Column("source", sa.String(), nullable=False, server_default="detail"))

    _add("verdicts", sa.Column("ust_sinir", sa.Integer(), nullable=True))
    _add("verdicts", sa.Column("trace", sa.JSON(), nullable=True))
    _add("verdicts", sa.Column("piyasa", sa.JSON(), nullable=True))
    _add("verdicts", sa.Column("beklemede", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add("verdicts", sa.Column("detail_json", sa.JSON(), nullable=True))
    _add("verdicts", sa.Column("findings_json", sa.JSON(), nullable=True))
    _add("verdicts", sa.Column("created_at", sa.DateTime(), nullable=True))

    if "events" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("ilan_no", sa.String(), nullable=True),
            sa.Column("watch_id", sa.Integer(), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_events_id", "events", ["id"])


def downgrade() -> None:
    op.drop_table("events")
