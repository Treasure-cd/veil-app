"""store WhatsApp replies for webhook delivery retries

Revision ID: c8d6a41f20b3
Revises: 5f3a90c2d7e1
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d6a41f20b3"
down_revision: Union[str, Sequence[str], None] = "5f3a90c2d7e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_messages",
        sa.Column("reply_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_messages", "replied_at")
    op.drop_column("whatsapp_messages", "reply_text")
