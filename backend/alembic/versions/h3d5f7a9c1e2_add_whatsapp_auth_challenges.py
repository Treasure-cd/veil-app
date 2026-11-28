"""add whatsapp_auth_challenges table

Revision ID: h3d5f7a9c1e2
Revises: g2c4d6e8f0a1
Create Date: 2026-11-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h3d5f7a9c1e2"
down_revision: Union[str, Sequence[str], None] = "g2c4d6e8f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_auth_challenges",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("code", sa.String(length=12), nullable=False, unique=True),
        sa.Column("phone_e164", sa.String(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index(
        "ix_whatsapp_auth_challenges_phone_e164",
        "whatsapp_auth_challenges",
        ["phone_e164"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_whatsapp_auth_challenges_user_id",
        "whatsapp_auth_challenges",
        ["user_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_auth_challenges_user_id", table_name="whatsapp_auth_challenges")
    op.drop_index("ix_whatsapp_auth_challenges_phone_e164", table_name="whatsapp_auth_challenges")
    op.drop_table("whatsapp_auth_challenges")
