"""add fiat_payments and fossapay_webhook_events tables

Revision ID: c4f9b2a17e12
Revises: 51d8b716a901
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f9b2a17e12"
down_revision: Union[str, Sequence[str], None] = "51d8b716a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fiat_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=True),
        sa.Column("flow", sa.String(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("fossapay_id", sa.String(), nullable=True),
        sa.Column("transaction_id", sa.String(), nullable=True),
        sa.Column("provider_reference", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("amount", sa.String(), nullable=False),
        sa.Column("fee", sa.String(), nullable=True),
        sa.Column("amount_payable", sa.String(), nullable=True),
        sa.Column("settlement_amount", sa.String(), nullable=True),
        sa.Column("total_debited", sa.String(), nullable=True),
        sa.Column("fee_bearer", sa.String(), nullable=True),
        sa.Column("route", sa.String(), nullable=True),
        sa.Column("split_code", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.String(), nullable=True),
        sa.Column("account_type", sa.String(), nullable=True),
        sa.Column("bank_code", sa.String(), nullable=True),
        sa.Column("bank_name", sa.String(), nullable=True),
        sa.Column("account_name", sa.String(), nullable=True),
        sa.Column("account_number", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payment_outcome", sa.String(), nullable=True),
        sa.Column("received_amount", sa.String(), nullable=True),
        sa.Column("last_event_id", sa.String(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["payment_intent_id"], ["payment_intents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fossapay_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_fiat_payments_flow", "fiat_payments", ["flow"], unique=False)
    op.create_index("ix_fiat_payments_fossapay_id", "fiat_payments", ["fossapay_id"], unique=True)
    op.create_index("ix_fiat_payments_idempotency_key", "fiat_payments", ["idempotency_key"], unique=True)
    op.create_index("ix_fiat_payments_payment_intent_id", "fiat_payments", ["payment_intent_id"], unique=False)
    op.create_index("ix_fiat_payments_reference", "fiat_payments", ["reference"], unique=True)
    op.create_index("ix_fiat_payments_status", "fiat_payments", ["status"], unique=False)
    op.create_index("ix_fiat_payments_transaction_id", "fiat_payments", ["transaction_id"], unique=False)
    op.create_index("ix_fiat_payments_user_id", "fiat_payments", ["user_id"], unique=False)

    op.create_table(
        "fossapay_webhook_events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_fossapay_webhook_events_event_type", "fossapay_webhook_events", ["event_type"], unique=False)
    op.create_index("ix_fossapay_webhook_events_reference", "fossapay_webhook_events", ["reference"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fossapay_webhook_events_reference", table_name="fossapay_webhook_events")
    op.drop_index("ix_fossapay_webhook_events_event_type", table_name="fossapay_webhook_events")
    op.drop_table("fossapay_webhook_events")

    op.drop_index("ix_fiat_payments_user_id", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_transaction_id", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_status", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_reference", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_payment_intent_id", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_idempotency_key", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_fossapay_id", table_name="fiat_payments")
    op.drop_index("ix_fiat_payments_flow", table_name="fiat_payments")
    op.drop_table("fiat_payments")
