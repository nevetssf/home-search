"""add property origin

Revision ID: 5808b1cb64da
Revises: a5f9cf00be98
Create Date: 2026-07-01 08:57:18.271854
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5808b1cb64da'
down_revision: Union[str, None] = 'a5f9cf00be98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("origin", sa.String(), nullable=True))
    op.create_index(op.f("ix_properties_origin"), "properties", ["origin"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_properties_origin"), table_name="properties")
    op.drop_column("properties", "origin")
