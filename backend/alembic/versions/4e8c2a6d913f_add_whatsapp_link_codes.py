"""add single-use WhatsApp account link codes

Revision ID: 4e8c2a6d913f
Revises: 2c4e8f1a7b90
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e8c2a6d913f"
down_revision: Union[str, Sequence[str], None] = "2c4e8f1a7b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_link_codes",
        sa.Column("code", sa.String(length=6), primary_key=True),
        sa.Column("merchant_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_whatsapp_link_codes_merchant_id", "whatsapp_link_codes", ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_link_codes_merchant_id", table_name="whatsapp_link_codes")
    op.drop_table("whatsapp_link_codes")
