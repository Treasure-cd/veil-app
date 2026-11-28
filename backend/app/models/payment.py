from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_aware() -> datetime:
    return datetime.now(timezone.utc)


class FiatPaymentFlow(StrEnum):
    CHECKOUT = "checkout"
    PAYOUT = "payout"


class FiatPaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    REVERSED = "reversed"


class SettlementTarget(StrEnum):
    CRYPTO = "crypto"
    FIAT = "fiat"


class PajOrderStatus(StrEnum):
    INIT = "INIT"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class MerchantBankAccount(SQLModel, table=True):
    """Nigerian bank account registered with Paj Cash for auto-offramp payouts."""

    __tablename__ = "merchant_bank_accounts"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., foreign_key="user.id", index=True)
    paj_account_id: str = Field(..., index=True)
    bank_code: str = Field(...)
    bank_name: str = Field(...)
    account_number: str = Field(..., index=True)
    account_name: str = Field(...)
    solana_address: str = Field(..., index=True)
    evm_address: Optional[str] = Field(default=None)
    is_default: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PaymentIntent(SQLModel, table=True):
    __tablename__ = "payment_intents"
    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., index=True)
    merchant_ref: str = Field(...)
    mint: str = Field(...)
    amount_atomic: str = Field(...)
    amount_ngn: Optional[str] = Field(default=None)
    rate_ngn_per_token: Optional[str] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    recipient_address: str = Field(...)
    receive_mode: str = Field(default="private")
    allow_fiat_checkout: bool = Field(default=True)
    settlement_target: str = Field(default=SettlementTarget.CRYPTO)
    bank_account_id: Optional[UUID] = Field(
        default=None, foreign_key="merchant_bank_accounts.id", index=True
    )
    memo: Optional[str] = Field(default=None)
    status: str = Field(default="created")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    fund_signature: Optional[str] = Field(default=None, index=True, unique=True)
    claim_signature: Optional[str] = Field(default=None)
    paid_via: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None)
    failure_reason: Optional[str] = Field(default=None)


class FiatPayment(SQLModel, table=True):
    """Tracks FossaPay NGN checkouts (collections) and master-wallet payouts."""

    __tablename__ = "fiat_payments"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., foreign_key="user.id", index=True)
    payment_intent_id: Optional[UUID] = Field(
        default=None, foreign_key="payment_intents.id", index=True
    )
    flow: str = Field(..., index=True)  # "checkout" | "payout"
    reference: str = Field(..., unique=True, index=True, max_length=100)
    idempotency_key: str = Field(..., unique=True, index=True, max_length=255)

    fossapay_id: Optional[str] = Field(default=None, unique=True, index=True)
    transaction_id: Optional[str] = Field(default=None, index=True)
    provider_reference: Optional[str] = Field(default=None)

    currency: str = Field(default="NGN")
    amount: str = Field(...)
    fee: Optional[str] = Field(default=None)
    amount_payable: Optional[str] = Field(default=None)
    settlement_amount: Optional[str] = Field(default=None)
    total_debited: Optional[str] = Field(default=None)
    fee_bearer: Optional[str] = Field(default=None)
    route: Optional[str] = Field(default=None)
    split_code: Optional[str] = Field(default=None)
    metadata_json: Optional[str] = Field(default=None)

    # Checkout virtual account details or payout beneficiary bank details
    account_type: Optional[str] = Field(default=None)
    bank_code: Optional[str] = Field(default=None)
    bank_name: Optional[str] = Field(default=None)
    account_name: Optional[str] = Field(default=None)
    account_number: Optional[str] = Field(default=None)

    status: str = Field(default=FiatPaymentStatus.PENDING, index=True)
    payment_outcome: Optional[str] = Field(default=None)
    received_amount: Optional[str] = Field(default=None)
    last_event_id: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None, max_length=255)
    failure_reason: Optional[str] = Field(default=None)

    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reversed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class FossaPayWebhookEvent(SQLModel, table=True):
    """Deduplication log for processed FossaPay webhook eventIds."""

    __tablename__ = "fossapay_webhook_events"

    event_id: str = Field(primary_key=True)
    event_type: str = Field(..., index=True)
    reference: Optional[str] = Field(default=None, index=True)
    received_at: datetime = Field(
        default_factory=utc_now_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PajOfframpOrder(SQLModel, table=True):
    """Tracks Paj Cash crypto-to-NGN offramp orders for fiat-settled merchants."""

    __tablename__ = "paj_offramp_orders"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., foreign_key="user.id", index=True)
    payment_intent_id: Optional[UUID] = Field(
        default=None, foreign_key="payment_intents.id", index=True
    )
    bank_account_id: Optional[UUID] = Field(
        default=None, foreign_key="merchant_bank_accounts.id", index=True
    )
    paj_order_id: Optional[str] = Field(default=None, unique=True, index=True)
    chain: str = Field(default="SOLANA")
    mint: str = Field(...)
    token_symbol: str = Field(...)
    token_decimals: int = Field(default=6)
    deposit_address: str = Field(..., index=True)
    token_amount: Optional[str] = Field(default=None)
    fiat_amount: Optional[str] = Field(default=None)
    currency: str = Field(default="NGN")
    rate: Optional[str] = Field(default=None)
    fee_usdc: Optional[str] = Field(default=None)
    bank_code: str = Field(...)
    bank_name: Optional[str] = Field(default=None)
    account_number: str = Field(...)
    account_name: Optional[str] = Field(default=None)
    status: str = Field(default=PajOrderStatus.INIT, index=True)
    tx_signature: Optional[str] = Field(default=None)
    narration: Optional[str] = Field(default=None, max_length=100)
    failure_reason: Optional[str] = Field(default=None)
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PaymentTraceEvent(SQLModel, table=True):
    """Immutable audit trail for payment creation, rail updates, webhooks, and admin recovery."""

    __tablename__ = "payment_trace_events"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    payment_intent_id: Optional[UUID] = Field(
        default=None, foreign_key="payment_intents.id", index=True
    )
    fiat_payment_id: Optional[UUID] = Field(
        default=None, foreign_key="fiat_payments.id", index=True
    )
    paj_order_id: Optional[UUID] = Field(
        default=None, foreign_key="paj_offramp_orders.id", index=True
    )
    payroll_group_id: Optional[UUID] = Field(
        default=None, foreign_key="payroll_groups.id", index=True
    )
    source: str = Field(..., index=True)
    event_type: str = Field(..., index=True)
    status: str = Field(default="info", index=True)
    summary: str = Field(...)
    details_json: Optional[str] = Field(default=None)
    actor_address: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
