"""add NGN pricing, locked rates and payment expiry

Revision ID: 51d8b716a901
Revises: 9b55648a04e1
Create Date: 2026-11-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "51d8b716a901"
down_revision: Union[str, Sequence[str], None] = "9b55648a04e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_intents", sa.Column("amount_ngn", sa.String(), nullable=True))
    op.add_column("payment_intents", sa.Column("rate_ngn_per_token", sa.String(), nullable=True))
    op.add_column("payment_intents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_groups", sa.Column("rate_ngn_per_token", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_groups", "rate_ngn_per_token")
    op.drop_column("payment_intents", "expires_at")
    op.drop_column("payment_intents", "rate_ngn_per_token")
    op.drop_column("payment_intents", "amount_ngn")
