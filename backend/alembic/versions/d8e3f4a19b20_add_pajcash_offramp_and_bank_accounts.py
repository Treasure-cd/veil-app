"""add pajcash merchant bank accounts, offramp orders, and intent settlement target

Revision ID: d8e3f4a19b20
Revises: c4f9b2a17e12
Create Date: 2026-11-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e3f4a19b20"
down_revision: Union[str, Sequence[str], None] = "c4f9b2a17e12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_bank_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("paj_account_id", sa.String(), nullable=False),
        sa.Column("bank_code", sa.String(), nullable=False),
        sa.Column("bank_name", sa.String(), nullable=False),
        sa.Column("account_number", sa.String(), nullable=False),
        sa.Column("account_name", sa.String(), nullable=False),
        sa.Column("solana_address", sa.String(), nullable=False),
        sa.Column("evm_address", sa.String(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_merchant_bank_accounts_user_id", "merchant_bank_accounts", ["user_id"], unique=False)
    op.create_index("ix_merchant_bank_accounts_paj_account_id", "merchant_bank_accounts", ["paj_account_id"], unique=False)
    op.create_index("ix_merchant_bank_accounts_account_number", "merchant_bank_accounts", ["account_number"], unique=False)
    op.create_index("ix_merchant_bank_accounts_solana_address", "merchant_bank_accounts", ["solana_address"], unique=False)
    op.create_index("ix_merchant_bank_accounts_is_default", "merchant_bank_accounts", ["is_default"], unique=False)

    op.add_column(
        "payment_intents",
        sa.Column("settlement_target", sa.String(), nullable=False, server_default="crypto"),
    )
    op.add_column(
        "payment_intents",
        sa.Column("bank_account_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_intents_bank_account_id",
        "payment_intents",
        "merchant_bank_accounts",
        ["bank_account_id"],
        ["id"],
    )
    op.create_index("ix_payment_intents_bank_account_id", "payment_intents", ["bank_account_id"], unique=False)

    op.create_table(
        "paj_offramp_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=True),
        sa.Column("bank_account_id", sa.Uuid(), nullable=True),
        sa.Column("paj_order_id", sa.String(), nullable=True),
        sa.Column("chain", sa.String(), nullable=False),
        sa.Column("mint", sa.String(), nullable=False),
        sa.Column("token_symbol", sa.String(), nullable=False),
        sa.Column("token_decimals", sa.Integer(), nullable=False),
        sa.Column("deposit_address", sa.String(), nullable=False),
        sa.Column("token_amount", sa.String(), nullable=True),
        sa.Column("fiat_amount", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("rate", sa.String(), nullable=True),
        sa.Column("fee_usdc", sa.String(), nullable=True),
        sa.Column("bank_code", sa.String(), nullable=False),
        sa.Column("bank_name", sa.String(), nullable=True),
        sa.Column("account_number", sa.String(), nullable=False),
        sa.Column("account_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("tx_signature", sa.String(), nullable=True),
        sa.Column("narration", sa.String(length=100), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["merchant_bank_accounts.id"]),
        sa.ForeignKeyConstraint(["payment_intent_id"], ["payment_intents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paj_order_id"),
    )
    op.create_index("ix_paj_offramp_orders_user_id", "paj_offramp_orders", ["user_id"], unique=False)
    op.create_index("ix_paj_offramp_orders_payment_intent_id", "paj_offramp_orders", ["payment_intent_id"], unique=False)
    op.create_index("ix_paj_offramp_orders_bank_account_id", "paj_offramp_orders", ["bank_account_id"], unique=False)
    op.create_index("ix_paj_offramp_orders_paj_order_id", "paj_offramp_orders", ["paj_order_id"], unique=True)
    op.create_index("ix_paj_offramp_orders_deposit_address", "paj_offramp_orders", ["deposit_address"], unique=False)
    op.create_index("ix_paj_offramp_orders_status", "paj_offramp_orders", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paj_offramp_orders_status", table_name="paj_offramp_orders")
    op.drop_index("ix_paj_offramp_orders_deposit_address", table_name="paj_offramp_orders")
    op.drop_index("ix_paj_offramp_orders_paj_order_id", table_name="paj_offramp_orders")
    op.drop_index("ix_paj_offramp_orders_bank_account_id", table_name="paj_offramp_orders")
    op.drop_index("ix_paj_offramp_orders_payment_intent_id", table_name="paj_offramp_orders")
    op.drop_index("ix_paj_offramp_orders_user_id", table_name="paj_offramp_orders")
    op.drop_table("paj_offramp_orders")

    op.drop_index("ix_payment_intents_bank_account_id", table_name="payment_intents")
    op.drop_constraint("fk_payment_intents_bank_account_id", "payment_intents", type_="foreignkey")
    op.drop_column("payment_intents", "bank_account_id")
    op.drop_column("payment_intents", "settlement_target")

    op.drop_index("ix_merchant_bank_accounts_is_default", table_name="merchant_bank_accounts")
    op.drop_index("ix_merchant_bank_accounts_solana_address", table_name="merchant_bank_accounts")
    op.drop_index("ix_merchant_bank_accounts_account_number", table_name="merchant_bank_accounts")
    op.drop_index("ix_merchant_bank_accounts_paj_account_id", table_name="merchant_bank_accounts")
    op.drop_index("ix_merchant_bank_accounts_user_id", table_name="merchant_bank_accounts")
    op.drop_table("merchant_bank_accounts")
