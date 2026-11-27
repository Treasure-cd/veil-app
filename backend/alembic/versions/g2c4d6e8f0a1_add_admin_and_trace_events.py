"""add admin role, payment trace events, and seed admin wallet

Revision ID: g2c4d6e8f0a1
Revises: e9b4a1c2d3f0, f1a7c9e32b4d
Create Date: 2026-11-28
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "g2c4d6e8f0a1"
down_revision: Union[str, Sequence[str], None] = ("e9b4a1c2d3f0", "f1a7c9e32b4d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_ADMIN_ADDRESS = "6sVpTNzecJcdenKmmr34BPUEBpYqSSe3QHKut4iiXvKY"


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "payment_trace_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "payment_intent_id",
            sa.Uuid(),
            sa.ForeignKey("payment_intents.id"),
            nullable=True,
        ),
        sa.Column(
            "fiat_payment_id",
            sa.Uuid(),
            sa.ForeignKey("fiat_payments.id"),
            nullable=True,
        ),
        sa.Column(
            "paj_order_id",
            sa.Uuid(),
            sa.ForeignKey("paj_offramp_orders.id"),
            nullable=True,
        ),
        sa.Column(
            "payroll_group_id",
            sa.Uuid(),
            sa.ForeignKey("payroll_groups.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("actor_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_trace_events_payment_intent_id", "payment_trace_events", ["payment_intent_id"])
    op.create_index("ix_payment_trace_events_fiat_payment_id", "payment_trace_events", ["fiat_payment_id"])
    op.create_index("ix_payment_trace_events_paj_order_id", "payment_trace_events", ["paj_order_id"])
    op.create_index("ix_payment_trace_events_payroll_group_id", "payment_trace_events", ["payroll_group_id"])
    op.create_index("ix_payment_trace_events_source", "payment_trace_events", ["source"])
    op.create_index("ix_payment_trace_events_event_type", "payment_trace_events", ["event_type"])
    op.create_index("ix_payment_trace_events_status", "payment_trace_events", ["status"])
    op.create_index("ix_payment_trace_events_actor_address", "payment_trace_events", ["actor_address"])
    op.create_index("ix_payment_trace_events_created_at", "payment_trace_events", ["created_at"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.execute(
        sa.text(
            'INSERT INTO "user" (id, address, is_admin, created_at, updated_at) '
            'VALUES (:id, :address, true, :created_at, :updated_at) '
            'ON CONFLICT (address) DO UPDATE SET is_admin = true, updated_at = :updated_at'
        ).bindparams(
            id=uuid4(),
            address=SEED_ADMIN_ADDRESS,
            created_at=now,
            updated_at=now,
        )
    )


def downgrade() -> None:
    op.drop_index("ix_payment_trace_events_created_at", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_actor_address", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_status", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_event_type", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_source", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_payroll_group_id", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_paj_order_id", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_fiat_payment_id", table_name="payment_trace_events")
    op.drop_index("ix_payment_trace_events_payment_intent_id", table_name="payment_trace_events")
    op.drop_table("payment_trace_events")
    op.drop_column("user", "is_admin")
