"""add WhatsApp setup tracking tokens

Revision ID: f1a7c9e32b4d
Revises: c8d6a41f20b3
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a7c9e32b4d"
down_revision: Union[str, Sequence[str], None] = "c8d6a41f20b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_setup_tokens",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("phone_e164", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_whatsapp_setup_tokens_phone_e164", "whatsapp_setup_tokens", ["phone_e164"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_setup_tokens_phone_e164", table_name="whatsapp_setup_tokens")
    op.drop_table("whatsapp_setup_tokens")
