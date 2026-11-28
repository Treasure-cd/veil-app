"""add payroll payout signatures

Revision ID: j5f7a9b1c3d4
Revises: i4e6f8a0b2c3
Create Date: 2026-11-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j5f7a9b1c3d4"
down_revision: Union[str, Sequence[str], None] = "i4e6f8a0b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_groups", sa.Column("payout_signatures_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_groups", "payout_signatures_json")
