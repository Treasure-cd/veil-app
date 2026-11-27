"""add per-intent FossaPay checkout option

Revision ID: 5f3a90c2d7e1
Revises: 4e8c2a6d913f, d8e3f4a19b20
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f3a90c2d7e1"
down_revision: Union[str, Sequence[str], None] = ("4e8c2a6d913f", "d8e3f4a19b20")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_intents",
        sa.Column("allow_fiat_checkout", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("payment_intents", "allow_fiat_checkout")
