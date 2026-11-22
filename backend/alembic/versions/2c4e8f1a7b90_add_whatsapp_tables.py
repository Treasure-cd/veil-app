"""add WhatsApp links, sessions, and inbound message idempotency

Revision ID: 2c4e8f1a7b90
Revises: 51d8b716a901
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2c4e8f1a7b90"
down_revision: Union[str, Sequence[str], None] = "51d8b716a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("phone_e164", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="code"),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_whatsapp_links_merchant_id", "whatsapp_links", ["merchant_id"])
    op.create_index("ix_whatsapp_links_phone_e164", "whatsapp_links", ["phone_e164"], unique=True)

    op.create_table(
        "whatsapp_sessions",
        sa.Column("phone_e164", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("draft_memo", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "whatsapp_messages",
        sa.Column("message_sid", sa.String(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("whatsapp_messages")
    op.drop_table("whatsapp_sessions")
    op.drop_index("ix_whatsapp_links_phone_e164", table_name="whatsapp_links")
    op.drop_index("ix_whatsapp_links_merchant_id", table_name="whatsapp_links")
    op.drop_table("whatsapp_links")
