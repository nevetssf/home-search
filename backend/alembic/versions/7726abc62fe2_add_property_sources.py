"""add property_sources

Revision ID: 7726abc62fe2
Revises: 5808b1cb64da
Create Date: 2026-07-01 09:33:53.680943
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7726abc62fe2'
down_revision: Union[str, None] = '5808b1cb64da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_property_source"),
    )
    op.create_index(op.f("ix_property_sources_id"), "property_sources", ["id"], unique=False)
    op.create_index(op.f("ix_property_sources_property_id"), "property_sources", ["property_id"], unique=False)
    op.create_index(op.f("ix_property_sources_source_id"), "property_sources", ["source_id"], unique=False)

    # Backfill: mirror each property's primary source into a PropertySource row.
    conn = op.get_bind()
    props = conn.execute(sa.text(
        "SELECT id, source, source_id, source_url, origin, last_synced_at FROM properties"
    )).fetchall()
    for p in props:
        conn.execute(
            sa.text(
                "INSERT INTO property_sources "
                "(property_id, source, source_id, source_url, origin, last_synced_at, created_at) "
                "VALUES (:pid, :src, :sid, :url, :origin, :synced, :synced)"
            ),
            {"pid": p[0], "src": p[1] or "manual", "sid": p[2], "url": p[3],
             "origin": p[4], "synced": p[5]},
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_property_sources_source_id"), table_name="property_sources")
    op.drop_index(op.f("ix_property_sources_property_id"), table_name="property_sources")
    op.drop_index(op.f("ix_property_sources_id"), table_name="property_sources")
    op.drop_table("property_sources")
