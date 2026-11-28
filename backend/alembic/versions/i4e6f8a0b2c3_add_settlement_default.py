"""add per-user settlement default

Revision ID: i4e6f8a0b2c3
Revises: h3d5f7a9c1e2
Create Date: 2026-11-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i4e6f8a0b2c3"
down_revision: Union[str, Sequence[str], None] = "h3d5f7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("default_settlement_target", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "default_settlement_target")
