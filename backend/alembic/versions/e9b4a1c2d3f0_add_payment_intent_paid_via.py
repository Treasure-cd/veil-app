"""add paid_via column to payment_intents

Revision ID: e9b4a1c2d3f0
Revises: c8d6a41f20b3
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9b4a1c2d3f0"
down_revision: Union[str, Sequence[str], None] = "c8d6a41f20b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_intents",
        sa.Column("paid_via", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_intents", "paid_via")
