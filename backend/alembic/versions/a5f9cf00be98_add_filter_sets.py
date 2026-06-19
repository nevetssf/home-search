"""add filter_sets

Revision ID: a5f9cf00be98
Revises: 3bdcce288120
Create Date: 2026-06-19 10:23:45.562937
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5f9cf00be98'
down_revision: Union[str, None] = '3bdcce288120'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "filter_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_filter_set_name"),
    )
    op.create_index(op.f("ix_filter_sets_id"), "filter_sets", ["id"], unique=False)
    op.create_index(op.f("ix_filter_sets_user_id"), "filter_sets", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_filter_sets_user_id"), table_name="filter_sets")
    op.drop_index(op.f("ix_filter_sets_id"), table_name="filter_sets")
    op.drop_table("filter_sets")
