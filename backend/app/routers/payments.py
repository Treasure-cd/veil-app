import asyncio
import logging
import time
from collections import defaultdict
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from decimal import Decimal, ROUND_DOWN

import base58
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.signature import Signature

from app.models.payment import (
    FiatPayment,
    FiatPaymentFlow,
    FiatPaymentStatus,
    MerchantBankAccount,
    PajOfframpOrder,
    PajOrderStatus,
    PaymentIntent,
    SettlementTarget,
    utc_now,
)
from app.models.user import User
from app.routers.dependencies import get_current_user, get_optional_user
from app.services.pajcash import PAJ_SOLANA_TOKENS, PajCashError, PajCashService
from app.services.payment import FossaPayError, FossaPayService
from app.services.payment_intents import create_payment_intent
from app.services.trace import record_trace_event
from core.config import settings
from core.session import get_session

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

logger = logging.getLogger(__name__)
_BANKS_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_PAJ_BANKS_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_BANKS_CACHE_TTL_SECONDS = 3600
UMBRA_PROGRAM_IDS = {
    "mainnet-beta": "UMBRAD2ishebJTcgCLkTkNUx1v3GyoAgpTRPeWoLykh",
    "devnet": "DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ",
}

class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    token: Literal["USDC", "SOL"]
    amount_ngn: Decimal = Field(validation_alias=AliasChoices("amount_ngn", "amountNgn"))
    recipientAddress: str
    receiveMode: Literal["private", "public"] = "private"
    allowFiatCheckout: bool = True
    settlementTarget: Literal["crypto", "fiat"] = "crypto"
    bankAccountId: Optional[UUID] = None
    memo: Optional[str] = None
    includeFiatCheckout: bool = False
    feeBearer: Literal["customer", "merchant"] = "customer"

    @model_validator(mode="after")
    def validate_recipient(self):
        # Fiat-settled intents are routed to the linked bank account's Paj
        # deposit address, so the merchant does not need a crypto wallet and
        # recipientAddress may be a non-Solana placeholder (e.g. WhatsApp-only accounts).
        if self.settlementTarget == SettlementTarget.CRYPTO.value:
            try:
                Pubkey.from_string(self.recipientAddress)
            except ValueError as exc:
                raise ValueError("Invalid Solana address") from exc
        return self

    @field_validator("amount_ngn")
    @classmethod
    def validate_amount(cls, v: Decimal):
        if not v.is_finite() or v <= 0:
            raise ValueError("amount_ngn must be a positive number")
        return v

class ConfirmFundRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)
    pajOfframpOrderId: Optional[UUID] = None

class ConfirmClaimRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)


class RegisterPajBankAccountRequest(BaseModel):
    bankCode: str = Field(min_length=1, max_length=100)
    accountNumber: str = Field(min_length=10, max_length=20)
    makeDefault: bool = True


class CreateIntentPajOfframpRequest(BaseModel):
    token: str = Field(default="USDC", min_length=1, max_length=64)


class ReconcilePajOfframpRequest(BaseModel):
    orderId: Optional[UUID] = None


class CreateFiatCheckoutRequest(BaseModel):
    amount_ngn: int = Field(ge=1, validation_alias=AliasChoices("amount_ngn", "amountNgn"))
    feeBearer: Literal["customer", "merchant"] = "customer"
    description: Optional[str] = Field(default=None, max_length=255)
    paymentIntentId: Optional[UUID] = None
    reference: Optional[str] = Field(default=None, min_length=1, max_length=100)
    idempotencyKey: Optional[str] = Field(default=None, min_length=1, max_length=255)


class BankNameEnquiryRequest(BaseModel):
    bankCode: str = Field(min_length=1, max_length=100)
    accountNumber: str = Field(min_length=10, max_length=20)


class CreateFiatPayoutRequest(BaseModel):
    amount_ngn: int = Field(ge=1, validation_alias=AliasChoices("amount_ngn", "amountNgn"))
    bankCode: str = Field(min_length=1, max_length=100)
    bankName: str = Field(min_length=1, max_length=199)
    accountNumber: str = Field(min_length=1, max_length=199)
    accountName: str = Field(min_length=1, max_length=199)
    remarks: Optional[str] = Field(default=None, max_length=255)
    paymentIntentId: Optional[UUID] = None
    reference: Optional[str] = Field(default=None, min_length=1, max_length=100)
    idempotencyKey: Optional[str] = Field(default=None, min_length=1, max_length=255)

def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid intent ID") from exc


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def format_fiat_payment(payment: FiatPayment, is_owner: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": str(payment.id),
        "paymentIntentId": str(payment.payment_intent_id) if payment.payment_intent_id else None,
        "flow": payment.flow,
        "reference": payment.reference,
        "currency": payment.currency,
        "amount": payment.amount,
        "fee": payment.fee,
        "amountPayable": payment.amount_payable,
        "feeBearer": payment.fee_bearer,
        "accountType": payment.account_type,
        "bankName": payment.bank_name,
        "accountName": payment.account_name,
        "accountNumber": payment.account_number,
        "status": payment.status,
        "paymentOutcome": payment.payment_outcome,
        "receivedAmount": payment.received_amount,
        "description": payment.description,
        "expiresAt": _utc_iso(payment.expires_at),
        "completedAt": _utc_iso(payment.completed_at),
        "failedAt": _utc_iso(payment.failed_at),
        "reversedAt": _utc_iso(payment.reversed_at),
        "createdAt": _utc_iso(payment.created_at),
    }
    if is_owner:
        data.update({
            "userId": str(payment.user_id),
            "fossapayId": payment.fossapay_id,
            "transactionId": payment.transaction_id,
            "providerReference": payment.provider_reference,
            "settlementAmount": payment.settlement_amount,
            "totalDebited": payment.total_debited,
            "route": payment.route,
            "bankCode": payment.bank_code,
            "failureReason": payment.failure_reason,
            "updatedAt": _utc_iso(payment.updated_at),
        })
    return data


def _raise_fossapay_http_error(exc: FossaPayError) -> None:
    status_code = exc.status_code if 400 <= exc.status_code < 500 else 502
    raise HTTPException(status_code=status_code, detail=exc.message) from exc


def _raise_paj_http_error(exc: PajCashError) -> None:
    status_code = exc.status_code if 400 <= exc.status_code < 500 else 502
    raise HTTPException(status_code=status_code, detail=exc.message) from exc


def format_bank_account(account: MerchantBankAccount, is_owner: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": str(account.id),
        "bankName": account.bank_name,
        "isDefault": account.is_default,
    }
    if is_owner:
        data.update({
            "userId": str(account.user_id),
            "pajAccountId": account.paj_account_id,
            "bankCode": account.bank_code,
            "accountNumber": account.account_number,
            "accountName": account.account_name,
            "solanaAddress": account.solana_address,
            "evmAddress": account.evm_address,
            "createdAt": _utc_iso(account.created_at),
            "updatedAt": _utc_iso(account.updated_at),
        })
    return data


def format_paj_offramp(order: PajOfframpOrder, is_owner: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": str(order.id),
        "paymentIntentId": str(order.payment_intent_id) if order.payment_intent_id else None,
        "chain": order.chain,
        "mint": order.mint,
        "tokenSymbol": order.token_symbol,
        "tokenDecimals": order.token_decimals,
        "depositAddress": order.deposit_address,
        "tokenAmount": order.token_amount,
        "fiatAmount": order.fiat_amount,
        "currency": order.currency,
        "rate": order.rate,
        "feeUsdc": order.fee_usdc,
        "status": order.status,
        "txSignature": order.tx_signature,
        "narration": order.narration,
        "expiresAt": _utc_iso(order.expires_at),
        "createdAt": _utc_iso(order.created_at),
    }
    if is_owner:
        data.update({
            "userId": str(order.user_id),
            "pajOrderId": order.paj_order_id,
            "bankAccountId": str(order.bank_account_id) if order.bank_account_id else None,
            "bankCode": order.bank_code,
            "bankName": order.bank_name,
            "accountNumber": order.account_number,
            "accountName": order.account_name,
            "failureReason": order.failure_reason,
            "updatedAt": _utc_iso(order.updated_at),
        })
    return data


_PAJ_STATUS_PRIORITY = {
    PajOrderStatus.COMPLETED.value: 0,
    PajOrderStatus.PROCESSING.value: 1,
    PajOrderStatus.INIT.value: 2,
    PajOrderStatus.ERROR.value: 3,
}


async def _latest_paj_offramp_for_intent(
    db: AsyncSession, intent_id: UUID
) -> PajOfframpOrder | None:
    stmt = (
        select(PajOfframpOrder)
        .where(PajOfframpOrder.payment_intent_id == intent_id)
        .order_by(PajOfframpOrder.updated_at.desc(), PajOfframpOrder.created_at.desc())
    )
    orders = (await db.execute(stmt)).scalars().all()
    if not orders:
        return None
    return min(orders, key=lambda o: _PAJ_STATUS_PRIORITY.get(o.status, 99))


async def _mark_pending_fiat_checkout_superseded(
    db: AsyncSession, intent_id: UUID, paid_via: str
) -> None:
    rows = (
        await db.execute(
            select(FiatPayment).where(
                FiatPayment.payment_intent_id == intent_id,
                FiatPayment.flow == FiatPaymentFlow.CHECKOUT.value,
                FiatPayment.status.in_(
                    (FiatPaymentStatus.PENDING.value, FiatPaymentStatus.PROCESSING.value)
                ),
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = FiatPaymentStatus.EXPIRED.value
        row.payment_outcome = f"paid_via_{paid_via}"
        row.failure_reason = f"Settled via {paid_via}"
        row.updated_at = utc_now()
        db.add(row)


async def mark_intent_funded_from_paj(
    db: AsyncSession, order: PajOfframpOrder
) -> PaymentIntent | None:
    if (
        order.status not in (PajOrderStatus.PROCESSING.value, PajOrderStatus.COMPLETED.value)
        or not order.payment_intent_id
    ):
        return None
    intent = await db.get(PaymentIntent, order.payment_intent_id)
    expired_candidate = intent is not None and intent.status == "failed" and intent.failure_reason == "expired"
    if intent and (intent.status in ("created", "funded") or expired_candidate):
        changed = False
        if intent.status == "created" or expired_candidate:
            intent.status = "funded"
            intent.failure_reason = None
            changed = True
        if intent.paid_via is None:
            intent.paid_via = "paj"
            changed = True
        if order.tx_signature and not intent.fund_signature:
            intent.fund_signature = order.tx_signature
            changed = True
        await _mark_pending_fiat_checkout_superseded(db, intent.id, "paj")
        if changed:
            intent.updated_at = utc_now()
            db.add(intent)
        await record_trace_event(
            db,
            source="paj",
            event_type="paj_order_funded" if changed else "paj_order_synced",
            summary=f"Paj order {order.paj_order_id or order.id} status={order.status}; intent status={intent.status}",
            status="ok",
            payment_intent_id=intent.id,
            paj_order_id=order.id,
            details={
                "pajOrderId": order.paj_order_id,
                "pajStatus": order.status,
                "txSignature": order.tx_signature,
                "intentStatus": intent.status,
            },
        )
        await db.commit()
        await db.refresh(intent)
    return intent


def _whole_ngn_from_intent(intent: PaymentIntent) -> int:
    if not intent.amount_ngn:
        raise HTTPException(
            status_code=400,
            detail="This payment request does not have an NGN amount for bank transfer.",
        )
    dec = Decimal(intent.amount_ngn)
    if not dec.is_finite() or dec != dec.to_integral_value() or dec < 1:
        raise HTTPException(
            status_code=400,
            detail="Bank transfer checkouts require a whole-naira amount of at least ₦1.",
        )
    return int(dec)


async def _latest_checkout_for_intent(
    db: AsyncSession, intent_id: UUID
) -> FiatPayment | None:
    stmt = (
        select(FiatPayment)
        .where(
            FiatPayment.payment_intent_id == intent_id,
            FiatPayment.flow == FiatPaymentFlow.CHECKOUT.value,
        )
        .order_by(FiatPayment.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _latest_payout_for_intent(
    db: AsyncSession, intent_id: UUID
) -> FiatPayment | None:
    stmt = (
        select(FiatPayment)
        .where(
            FiatPayment.payment_intent_id == intent_id,
            FiatPayment.flow == FiatPaymentFlow.PAYOUT.value,
        )
        .order_by(FiatPayment.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _settle_fiat_intent_payout(
    db: AsyncSession,
    intent: PaymentIntent,
    checkout: FiatPayment,
    *,
    allow_retry: bool = False,
    actor_address: str | None = None,
) -> FiatPayment | None:
    """When a fiat-settled intent is paid by bank transfer, disburse NGN to the merchant's linked bank."""
    if intent.settlement_target != SettlementTarget.FIAT.value or not intent.bank_account_id:
        return None

    existing = await _latest_payout_for_intent(db, intent.id)
    if existing is not None:
        if existing.status == FiatPaymentStatus.COMPLETED.value:
            return existing
        if existing.status in (
            FiatPaymentStatus.PENDING.value,
            FiatPaymentStatus.PROCESSING.value,
        ) and (existing.fossapay_id or not allow_retry):
            return existing
        if not allow_retry:
            return existing

    bank_account = await db.get(MerchantBankAccount, intent.bank_account_id)
    if bank_account is None:
        await record_trace_event(
            db,
            source="fossapay",
            event_type="fossapay_payout_skipped",
            summary="Auto-payout skipped because linked bank account was not found",
            status="error",
            payment_intent_id=intent.id,
            fiat_payment_id=checkout.id,
            actor_address=actor_address,
            commit=True,
        )
        return None

    try:
        raw_amount = Decimal(str(checkout.settlement_amount or checkout.amount))
        payout_ngn = int(raw_amount.to_integral_value(rounding=ROUND_DOWN))
    except Exception:
        return None
    if payout_ngn < 1:
        return None

    if existing is None:
        reference = f"SETTLE-{intent.id.hex[:20]}"
        idempotency_key = f"intent-fiat-settle:{intent.id}"
    else:
        prior_count = len(
            (
                await db.execute(
                    select(FiatPayment.id).where(
                        FiatPayment.payment_intent_id == intent.id,
                        FiatPayment.flow == FiatPaymentFlow.PAYOUT.value,
                    )
                )
            ).all()
        )
        attempt_num = prior_count + 1
        reference = f"SETTLE-{intent.id.hex[:14]}-R{attempt_num}"
        idempotency_key = f"intent-fiat-settle:{intent.id}:r{attempt_num}"

    try:
        payout = await FossaPayService().create_payout(
            db,
            user_id=intent.user_id,
            payment_intent_id=intent.id,
            amount_ngn=payout_ngn,
            reference=reference,
            bank_code=bank_account.bank_code,
            bank_name=bank_account.bank_name,
            account_name=bank_account.account_name,
            account_number=bank_account.account_number,
            remarks=(intent.memo or intent.merchant_ref)[:255],
            idempotency_key=idempotency_key,
        )
        await record_trace_event(
            db,
            source="fossapay",
            event_type="fossapay_payout_retried" if existing is not None else "fossapay_payout_initiated",
            summary=f"FossaPay payout ₦{payout_ngn} to {bank_account.bank_name} ({payout.status})",
            status="ok" if payout.status == FiatPaymentStatus.COMPLETED.value else "info",
            payment_intent_id=intent.id,
            fiat_payment_id=payout.id,
            actor_address=actor_address,
            details={
                "reference": reference,
                "fossapayId": payout.fossapay_id,
                "bankName": bank_account.bank_name,
                "amountNgn": payout_ngn,
                "status": payout.status,
            },
            commit=True,
        )
        return payout
    except Exception as exc:
        logger.exception("Auto-payout settlement failed for fiat intent %s", intent.id)
        await record_trace_event(
            db,
            source="fossapay",
            event_type="fossapay_payout_failed",
            summary=f"FossaPay payout failed ({type(exc).__name__}): {exc}",
            status="error",
            payment_intent_id=intent.id,
            fiat_payment_id=checkout.id,
            actor_address=actor_address,
            details={
                "reference": reference,
                "bankAccountId": str(bank_account.id),
                "amountNgn": payout_ngn,
                "error": str(exc),
            },
            commit=True,
        )
        return None


async def mark_intent_funded_from_fiat(
    db: AsyncSession, payment: FiatPayment
) -> PaymentIntent | None:
    if (
        payment.flow != FiatPaymentFlow.CHECKOUT.value
        or payment.status != FiatPaymentStatus.COMPLETED.value
        or not payment.payment_intent_id
    ):
        return None
    intent = await db.get(PaymentIntent, payment.payment_intent_id)
    expired_candidate = intent is not None and intent.status == "failed" and intent.failure_reason == "expired"
    if intent and (intent.status == "created" or expired_candidate):
        intent.status = "funded"
        intent.failure_reason = None
        intent.paid_via = "fossapay"
        intent.updated_at = utc_now()
        db.add(intent)
        await record_trace_event(
            db,
            source="fossapay",
            event_type="fossapay_checkout_completed",
            summary=f"FossaPay bank checkout {payment.reference} completed -> intent funded",
            status="ok",
            payment_intent_id=intent.id,
            fiat_payment_id=payment.id,
            details={
                "reference": payment.reference,
                "fossapayId": payment.fossapay_id,
                "amount": payment.amount,
                "receivedAmount": payment.received_amount,
                "recoveredFromExpired": expired_candidate,
            },
        )
        await db.commit()
        await db.refresh(intent)
    if intent is not None:
        await _settle_fiat_intent_payout(db, intent, payment)
    return intent


def _paj_expected_atomic(order: PajOfframpOrder) -> str | None:
    if not order.token_amount:
        return None
    try:
        return str(
            int(
                (Decimal(order.token_amount) * (Decimal(10) ** order.token_decimals)).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
        )
    except Exception:
        return None


async def _reconcile_intent_paj_orders(
    db: AsyncSession, intent: PaymentIntent
) -> list[PajOfframpOrder]:
    orders = (
        await db.execute(
            select(PajOfframpOrder)
            .where(PajOfframpOrder.payment_intent_id == intent.id)
            .order_by(PajOfframpOrder.updated_at.desc(), PajOfframpOrder.created_at.desc())
        )
    ).scalars().all()
    service = PajCashService()
    updated_orders: list[PajOfframpOrder] = []
    for order in orders:
        if order.paj_order_id and order.status in (
            PajOrderStatus.INIT.value,
            PajOrderStatus.PROCESSING.value,
        ):
            try:
                order = await service.reconcile_offramp_order(db, order)
            except (PajCashError, ValueError) as exc:
                logger.warning("Paj offramp reconcile failed for order %s: %s", order.id, exc)
        if order.status in (
            PajOrderStatus.PROCESSING.value,
            PajOrderStatus.COMPLETED.value,
        ):
            await mark_intent_funded_from_paj(db, order)
        updated_orders.append(order)
    return updated_orders


_ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
_SPL_TOKEN_PROGRAM_IDS = (
    Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
    Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"),
)


def _query_pubkeys_for_transfer(owner_address: str, mint: str) -> list[Pubkey]:
    owner_pk = Pubkey.from_string(owner_address)
    pubkeys = [owner_pk]
    if mint != settings.SOL_MINT:
        mint_pk = Pubkey.from_string(mint)
        for token_prog_pk in _SPL_TOKEN_PROGRAM_IDS:
            ata, _ = Pubkey.find_program_address(
                [bytes(owner_pk), bytes(token_prog_pk), bytes(mint_pk)],
                _ASSOCIATED_TOKEN_PROGRAM_ID,
            )
            pubkeys.append(ata)
    return pubkeys


async def _find_matching_onchain_transfer(
    db: AsyncSession, intent: PaymentIntent, paj_orders: list[PajOfframpOrder]
) -> bool:
    expired_candidate = intent.status == "failed" and intent.failure_reason == "expired"
    if (intent.status != "created" and not expired_candidate) or intent.receive_mode == "private":
        return False

    targets: list[tuple[str, str, str, PajOfframpOrder | None]] = []
    seen_targets: set[tuple[str, str, str]] = set()
    for order in paj_orders:
        atomic = _paj_expected_atomic(order)
        if atomic and order.deposit_address:
            key = (order.deposit_address, order.mint, atomic)
            if key not in seen_targets:
                seen_targets.add(key)
                targets.append((order.deposit_address, order.mint, atomic, order))
    direct_key = (intent.recipient_address, intent.mint, intent.amount_atomic)
    if direct_key not in seen_targets:
        targets.append((intent.recipient_address, intent.mint, intent.amount_atomic, None))

    expected_memo = f"veil:{intent.id}"
    seen_sigs: set[str] = set()
    try:
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            for address, mint, atomic, matched_order in targets:
                try:
                    pubkeys = _query_pubkeys_for_transfer(address, mint)
                except Exception as exc:
                    logger.warning("Failed to derive transfer lookup addresses for %s: %s", address, exc)
                    continue
                entries = []
                for pubkey in pubkeys:
                    try:
                        sig_resp = await client.get_signatures_for_address(pubkey, limit=10)
                        entries.extend(sig_resp.value or [])
                    except Exception as exc:
                        logger.warning("Failed to list signatures for %s: %s", pubkey, exc)
                for entry in entries:
                    if getattr(entry, "err", None) is not None:
                        continue
                    sig_str = str(entry.signature)
                    if sig_str in seen_sigs:
                        continue
                    seen_sigs.add(sig_str)
                    duplicate = await db.execute(
                        select(PaymentIntent.id).where(PaymentIntent.fund_signature == sig_str)
                    )
                    if duplicate.first():
                        continue
                    if await verify_transfer(
                        sig_str,
                        mint,
                        address,
                        atomic,
                        intent.created_at,
                        expected_memo=expected_memo,
                        before=intent.expires_at,
                    ):
                        paid_via = "paj" if matched_order is not None else "crypto"
                        intent.status = "funded"
                        intent.failure_reason = None
                        intent.fund_signature = sig_str
                        intent.paid_via = paid_via
                        intent.updated_at = utc_now()
                        db.add(intent)
                        if matched_order is not None:
                            matched_order.tx_signature = sig_str
                            if matched_order.status == PajOrderStatus.INIT.value:
                                matched_order.status = PajOrderStatus.PROCESSING.value
                            matched_order.updated_at = utc_now()
                            db.add(matched_order)
                        await _mark_pending_fiat_checkout_superseded(db, intent.id, paid_via)
                        await record_trace_event(
                            db,
                            source="reconcile",
                            event_type="onchain_reconciled",
                            summary=f"Matched Solana transfer {sig_str[:12]}... ({paid_via})",
                            status="warn" if (intent.settlement_target == SettlementTarget.FIAT.value and matched_order is None) else "ok",
                            payment_intent_id=intent.id,
                            paj_order_id=matched_order.id if matched_order is not None else None,
                            details={
                                "signature": sig_str,
                                "paidVia": paid_via,
                                "targetAddress": address,
                                "mint": mint,
                                "amountAtomic": atomic,
                            },
                        )
                        await db.commit()
                        await db.refresh(intent)
                        return True
    except Exception as exc:
        logger.warning("On-chain reconciliation failed for intent %s: %s", intent.id, exc)
    return False


async def _reconcile_intent_all_rails(
    db: AsyncSession, intent: PaymentIntent
) -> tuple[
    PaymentIntent,
    FiatPayment | None,
    PajOfframpOrder | None,
    FiatPayment | None,
    MerchantBankAccount | None,
]:
    paj_orders = await _reconcile_intent_paj_orders(db, intent)
    refreshed = await db.get(PaymentIntent, intent.id)
    if refreshed is not None:
        intent = refreshed

    expired_candidate = intent.status == "failed" and intent.failure_reason == "expired"
    if (intent.status == "created" or expired_candidate) and intent.receive_mode != "private":
        await _find_matching_onchain_transfer(db, intent, paj_orders)
        refreshed = await db.get(PaymentIntent, intent.id)
        if refreshed is not None:
            intent = refreshed

    fiat_checkout = await _latest_checkout_for_intent(db, intent.id)
    expired_candidate = intent.status == "failed" and intent.failure_reason == "expired"
    if fiat_checkout is not None and fiat_checkout.status in (
        FiatPaymentStatus.PENDING.value,
        FiatPaymentStatus.PROCESSING.value,
    ):
        if intent.status in ("funded", "claimed") and intent.paid_via in ("paj", "crypto"):
            await _mark_pending_fiat_checkout_superseded(db, intent.id, intent.paid_via)
            await db.commit()
            await db.refresh(fiat_checkout)
        elif intent.status == "created" or expired_candidate:
            try:
                fiat_checkout = await FossaPayService().reconcile_checkout(db, fiat_checkout)
                await mark_intent_funded_from_fiat(db, fiat_checkout)
                refreshed = await db.get(PaymentIntent, intent.id)
                if refreshed is not None:
                    intent = refreshed
            except FossaPayError as exc:
                logger.warning("FossaPay checkout reconcile failed for intent %s: %s", intent.id, exc)
    elif (
        fiat_checkout is not None
        and fiat_checkout.status == FiatPaymentStatus.COMPLETED.value
        and (intent.status == "created" or expired_candidate)
    ):
        await mark_intent_funded_from_fiat(db, fiat_checkout)
        refreshed = await db.get(PaymentIntent, intent.id)
        if refreshed is not None:
            intent = refreshed

    fiat_payout = await _latest_payout_for_intent(db, intent.id)
    if fiat_payout is not None and fiat_payout.status in (
        FiatPaymentStatus.PENDING.value,
        FiatPaymentStatus.PROCESSING.value,
    ):
        try:
            fiat_payout = await FossaPayService().reconcile_payout(db, fiat_payout)
        except FossaPayError as exc:
            logger.warning("FossaPay payout reconcile failed for intent %s: %s", intent.id, exc)
    elif (
        fiat_payout is None
        and intent.settlement_target == SettlementTarget.FIAT.value
        and intent.status in ("funded", "claimed")
        and intent.paid_via == "fossapay"
        and fiat_checkout is not None
        and fiat_checkout.status == FiatPaymentStatus.COMPLETED.value
    ):
        fiat_payout = await _settle_fiat_intent_payout(db, intent, fiat_checkout)

    paj_offramp = await _latest_paj_offramp_for_intent(db, intent.id)
    bank_account = (
        await db.get(MerchantBankAccount, intent.bank_account_id)
        if intent.bank_account_id
        else None
    )
    return intent, fiat_checkout, paj_offramp, fiat_payout, bank_account

def format_intent(
    intent: PaymentIntent,
    is_owner: bool = True,
    fiat_checkout: FiatPayment | None = None,
    paj_offramp: PajOfframpOrder | None = None,
    bank_account: MerchantBankAccount | None = None,
    fiat_payout: FiatPayment | None = None,
) -> dict:
    data = {
        "id": str(intent.id),
        "merchantRef": intent.merchant_ref,
        "mint": intent.mint,
        "amountAtomic": intent.amount_atomic,
        "amount_ngn": intent.amount_ngn,
        "amount_token": None,
        "rate_ngn_per_token": intent.rate_ngn_per_token,
        "expires_at": intent.expires_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if intent.expires_at else None,
        "recipientAddress": intent.recipient_address,
        "receiveMode": intent.receive_mode,
        "allowFiatCheckout": intent.allow_fiat_checkout,
        "settlementTarget": intent.settlement_target,
        "paidVia": intent.paid_via,
        "memo": intent.memo,
        "status": intent.status,
        "createdAt": intent.created_at.isoformat() + "Z",
        "fiatCheckout": (
            format_fiat_payment(fiat_checkout, is_owner=is_owner)
            if fiat_checkout is not None
            else None
        ),
        "pajOfframp": (
            format_paj_offramp(paj_offramp, is_owner=is_owner)
            if paj_offramp is not None
            else None
        ),
        "bankAccount": (
            format_bank_account(bank_account, is_owner=is_owner)
            if bank_account is not None
            else None
        ),
        "fiatPayout": (
            format_fiat_payment(fiat_payout, is_owner=True)
            if is_owner and fiat_payout is not None
            else (
                {"status": fiat_payout.status, "bankName": fiat_payout.bank_name}
                if fiat_payout is not None
                else None
            )
        ),
    }
    if intent.receive_mode != "private":
        data["fundSignature"] = intent.fund_signature
    # Only show these fields to the merchant who owns the intent
    if is_owner:
        data.update({
            "userId": str(intent.user_id),
            "updatedAt": intent.updated_at.isoformat() + "Z",
            "claimSignature": intent.claim_signature,
            "failureReason": intent.failure_reason
        })
    token_decimals = 6 if intent.mint in settings.known_usdc_mints else 9
    data["amount_token"] = format(Decimal(intent.amount_atomic) / Decimal(10 ** token_decimals), "f")
    return data

async def verify_transfer(
    signature_str: str,
    mint: str,
    address: str,
    amount_atomic: str,
    after: datetime,
    direction: Literal["in", "out"] = "in",
    expected_memo: str | None = None,
    before: datetime | None = None,
) -> bool:
    try:
        sig = Signature.from_string(signature_str)
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            tx = None
            for attempt in range(6):
                response = await client.get_transaction(
                    sig,
                    encoding="jsonParsed",
                    commitment=Confirmed,
                    max_supported_transaction_version=1,
                )
                tx = response.value
                if tx is not None:
                    break
                if attempt < 5:
                    await asyncio.sleep(1.5)

        if tx is None:
            logger.warning("transaction not visible for signature %s", signature_str)
            return False
        if tx.transaction.meta is None:
            logger.warning("transaction metadata missing for signature %s", signature_str)
            return False

        meta = tx.transaction.meta
        if meta.err is not None:
            logger.warning("transaction failed on-chain for signature %s: %s", signature_str, meta.err)
            return False

        after_utc = (
            after.replace(tzinfo=timezone.utc)
            if after.tzinfo is None
            else after.astimezone(timezone.utc)
        )
        created_ts = after_utc.timestamp()
        if tx.block_time is None:
            logger.warning("block time missing for signature %s", signature_str)
            return False
        if tx.block_time < created_ts - 60:
            logger.warning("transaction predates intent for signature %s", signature_str)
            return False
        if before is not None:
            expiry_utc = before.replace(tzinfo=timezone.utc) if before.tzinfo is None else before.astimezone(timezone.utc)
            if tx.block_time >= expiry_utc.timestamp():
                logger.warning("transaction occurred after intent expiry for signature %s", signature_str)
                return False

        if expected_memo is not None:
            instructions = list(tx.transaction.transaction.message.instructions)
            for inner_group in meta.inner_instructions or []:
                instructions.extend(inner_group.instructions)
            memo_programs = {
                "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
                "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
            }

            def memo_matches(instruction) -> bool:
                if str(getattr(instruction, "program_id", "")) not in memo_programs:
                    return False
                parsed = getattr(instruction, "parsed", None)
                if parsed == expected_memo:
                    return True
                if isinstance(parsed, dict):
                    values = [parsed]
                    while values:
                        value = values.pop()
                        if value == expected_memo:
                            return True
                        if isinstance(value, dict):
                            values.extend(value.values())
                        elif isinstance(value, list):
                            values.extend(value)
                data = getattr(instruction, "data", None)
                if data:
                    try:
                        return base58.b58decode(data).decode("utf-8") == expected_memo
                    except (ValueError, UnicodeDecodeError):
                        return False
                return False

            has_intent_memo = any(memo_matches(instruction) for instruction in instructions)
            if not has_intent_memo:
                logger.warning("intent memo missing for signature %s", signature_str)
                return False

        if mint == settings.SOL_MINT:
            account_keys = list(tx.transaction.transaction.message.account_keys)
            loaded = getattr(meta, "loaded_addresses", None)
            if loaded is not None:
                account_keys.extend(getattr(loaded, "writable", None) or [])
                account_keys.extend(getattr(loaded, "readonly", None) or [])
            delta = 0
            for idx, key in enumerate(account_keys):
                pubkey_str = str(getattr(key, "pubkey", key))
                if pubkey_str == address and idx < len(meta.post_balances) and idx < len(meta.pre_balances):
                    delta += int(meta.post_balances[idx]) - int(meta.pre_balances[idx])
        else:
            def balance(entries) -> int:
                total = 0
                for entry in entries or []:
                    if str(entry.mint) == mint and str(entry.owner) == address:
                        total += int(entry.ui_token_amount.amount)
                return total

            delta = balance(meta.post_token_balances) - balance(meta.pre_token_balances)

        received = delta if direction == "in" else -delta
        if received != int(amount_atomic):
            logger.warning("amount mismatch: expected %s got %s", amount_atomic, received)
            return False
        return True
    except Exception:
        logger.exception("verify_transfer failed for %s", signature_str)
        return False

async def verify_umbra_deposit(
    signature_str: str,
    mint: str,
    amount_atomic: str,
    after: datetime,
    before: datetime | None = None,
) -> bool:
    network = settings.SOLANA_NETWORK.lower()
    if network == "mainnet":
        network = "mainnet-beta"
    expected_program = UMBRA_PROGRAM_IDS.get(network)
    if expected_program is None:
        logger.error("Unsupported Solana network for Umbra verification: %s", network)
        return False

    try:
        sig = Signature.from_string(signature_str)
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            tx = None
            for attempt in range(6):
                response = await client.get_transaction(
                    sig,
                    encoding="jsonParsed",
                    commitment=Confirmed,
                    max_supported_transaction_version=1,
                )
                tx = response.value
                if tx is not None:
                    break
                if attempt < 5:
                    await asyncio.sleep(1.5)

        if tx is None or tx.transaction.meta is None:
            logger.warning("Umbra transaction metadata unavailable for signature %s", signature_str)
            return False
        meta = tx.transaction.meta
        if meta.err is not None:
            logger.warning("Umbra transaction failed on-chain for signature %s", signature_str)
            return False
        if tx.block_time is None:
            logger.warning("Block time missing for Umbra signature %s", signature_str)
            return False

        after_utc = after.replace(tzinfo=timezone.utc) if after.tzinfo is None else after.astimezone(timezone.utc)
        if tx.block_time < after_utc.timestamp() - 60:
            logger.warning("Umbra transaction predates intent for signature %s", signature_str)
            return False
        if before is not None:
            expiry_utc = before.replace(tzinfo=timezone.utc) if before.tzinfo is None else before.astimezone(timezone.utc)
            if tx.block_time >= expiry_utc.timestamp():
                logger.warning("Umbra transaction occurred after intent expiry for signature %s", signature_str)
                return False

        instructions = list(tx.transaction.transaction.message.instructions)
        for inner_group in meta.inner_instructions or []:
            instructions.extend(inner_group.instructions)
        if not any(
            str(getattr(instruction, "program_id", "")) == expected_program
            for instruction in instructions
        ):
            logger.warning("Umbra program invocation missing for signature %s", signature_str)
            return False

        token_deltas: dict[str, int] = defaultdict(int)
        for entries, sign in ((meta.pre_token_balances, -1), (meta.post_token_balances, 1)):
            for entry in entries or []:
                if str(entry.mint) == mint and entry.owner:
                    token_deltas[str(entry.owner)] += sign * int(entry.ui_token_amount.amount)
        if -int(amount_atomic) not in token_deltas.values():
            logger.warning(
                "Umbra token debit mismatch for signature %s; expected %s %s",
                signature_str,
                amount_atomic,
                mint,
            )
            return False
        return True
    except Exception:
        logger.exception("verify_umbra_deposit failed for %s", signature_str)
        return False

async def _ensure_intent_fiat_checkout(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    fee_bearer: Literal["customer", "merchant"] = "customer",
) -> FiatPayment:
    existing = await _latest_checkout_for_intent(db, intent.id)
    if existing and existing.status in (
        FiatPaymentStatus.PENDING.value,
        FiatPaymentStatus.PROCESSING.value,
        FiatPaymentStatus.COMPLETED.value,
    ):
        return existing

    amount_ngn = _whole_ngn_from_intent(intent)
    reference = f"CHK-{intent.id.hex[:16]}-{uuid4().hex[:6]}"
    service = FossaPayService()
    try:
        payment = await service.create_checkout(
            db,
            user_id=intent.user_id,
            payment_intent_id=intent.id,
            amount_ngn=amount_ngn,
            reference=reference,
            fee_bearer=fee_bearer,
            description=(intent.memo or intent.merchant_ref)[:255],
            metadata={
                "paymentIntentId": str(intent.id),
                "merchantRef": intent.merchant_ref,
            },
        )
        await record_trace_event(
            db,
            source="fossapay",
            event_type="fossapay_checkout_created",
            summary=f"Created FossaPay bank checkout {payment.reference} ({payment.bank_name or 'virtual account'})",
            status="info",
            payment_intent_id=intent.id,
            fiat_payment_id=payment.id,
            details={
                "reference": payment.reference,
                "fossapayId": payment.fossapay_id,
                "amount": payment.amount,
                "accountNumber": payment.account_number,
                "bankName": payment.bank_name,
            },
            commit=True,
        )
        return payment
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)


@router.post("/intents")
async def create_intent(
    req: CreatePaymentIntentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    if req.includeFiatCheckout and not req.allowFiatCheckout:
        raise HTTPException(
            status_code=400,
            detail="Cannot create a bank-transfer checkout when FossaPay is disabled.",
        )
    if req.includeFiatCheckout:
        dec = req.amount_ngn
        if not dec.is_finite() or dec != dec.to_integral_value() or dec < 1:
            raise HTTPException(
                status_code=400,
                detail="Bank transfer checkouts require a whole-naira amount of at least ₦1.",
            )

    recipient_address = req.recipientAddress
    receive_mode = req.receiveMode
    bank_account: MerchantBankAccount | None = None

    if req.settlementTarget == SettlementTarget.FIAT.value:
        if req.bankAccountId is not None:
            bank_account = await db.get(MerchantBankAccount, req.bankAccountId)
            if not bank_account or bank_account.user_id != current_user.id:
                raise HTTPException(status_code=404, detail="bank_account_not_found")
        else:
            bank_account = (
                await db.execute(
                    select(MerchantBankAccount)
                    .where(MerchantBankAccount.user_id == current_user.id)
                    .order_by(MerchantBankAccount.is_default.desc(), MerchantBankAccount.created_at.desc())
                )
            ).scalars().first()
            if not bank_account:
                raise HTTPException(
                    status_code=400,
                    detail="Register a Nigerian bank account before creating a fiat-settled request.",
                )
        # Route on-chain deposits directly to Paj Cash's bank-account Solana address.
        recipient_address = bank_account.solana_address
        receive_mode = "public"

    if receive_mode == "private" and req.includeFiatCheckout:
        raise HTTPException(
            status_code=400,
            detail="Private Umbra payment links cannot include a bank-transfer checkout.",
        )

    intent = await create_payment_intent(
        db=db,
        user_id=current_user.id,
        recipient_address=recipient_address,
        amount_ngn=req.amount_ngn,
        merchant_ref=req.merchantRef,
        token=req.token,
        memo=req.memo,
        source="web",
        receive_mode=receive_mode,
        allow_fiat_checkout=req.allowFiatCheckout,
        settlement_target=req.settlementTarget,
        bank_account_id=bank_account.id if bank_account else None,
    )
    fiat_checkout: FiatPayment | None = None
    if req.includeFiatCheckout:
        fiat_checkout = await _ensure_intent_fiat_checkout(
            db, intent, fee_bearer=req.feeBearer
        )
    return format_intent(
        intent,
        is_owner=True,
        fiat_checkout=fiat_checkout,
        bank_account=bank_account,
    )

@router.get("/intents/{intent_id}")
async def get_intent(
    intent_id: str,
    current_user: Optional[User] = Depends(get_optional_user), # Can be called by anyone (e.g., a customer viewing a checkout page)
    db: AsyncSession = Depends(get_session)
):
    uuid_id = parse_uuid(intent_id)

    stmt = select(PaymentIntent).where(PaymentIntent.id == uuid_id)
    res = await db.execute(stmt)
    intent = res.scalars().first()

    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    expiry_utc = intent.expires_at.replace(tzinfo=timezone.utc) if intent.expires_at and intent.expires_at.tzinfo is None else intent.expires_at
    if intent.status == "created" and expiry_utc and datetime.now(timezone.utc) >= expiry_utc:
        intent.status = "failed"
        intent.failure_reason = "expired"
        intent.updated_at = utc_now()
        await record_trace_event(
            db,
            source="intent",
            event_type="intent_expired",
            summary="Payment request expired before settlement",
            status="warn",
            payment_intent_id=intent.id,
        )
        await db.commit()
        await db.refresh(intent)

    fiat_checkout = await _latest_checkout_for_intent(db, intent.id)
    paj_offramp = await _latest_paj_offramp_for_intent(db, intent.id)
    fiat_payout = await _latest_payout_for_intent(db, intent.id)
    bank_account = (
        await db.get(MerchantBankAccount, intent.bank_account_id)
        if intent.bank_account_id
        else None
    )
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_intent(
        intent,
        is_owner=is_owner,
        fiat_checkout=fiat_checkout,
        paj_offramp=paj_offramp,
        bank_account=bank_account,
        fiat_payout=fiat_payout,
    )


@router.post("/intents/{intent_id}/paj-offramp")
async def create_intent_paj_offramp(
    intent_id: str,
    req: CreateIntentPajOfframpRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")
    if intent.settlement_target != SettlementTarget.FIAT.value or not intent.bank_account_id:
        raise HTTPException(
            status_code=409,
            detail="This payment request settles in crypto directly; Paj offramp is not enabled.",
        )

    expiry_utc = intent.expires_at.replace(tzinfo=timezone.utc) if intent.expires_at and intent.expires_at.tzinfo is None else intent.expires_at
    if intent.status == "created" and expiry_utc and datetime.now(timezone.utc) >= expiry_utc:
        intent.status = "failed"
        intent.failure_reason = "expired"
        intent.updated_at = utc_now()
        await db.commit()
        raise HTTPException(status_code=409, detail="This payment request has expired.")

    if intent.status != "created":
        existing = await _latest_paj_offramp_for_intent(db, intent.id)
        if existing:
            is_owner = current_user is not None and intent.user_id == current_user.id
            return format_paj_offramp(existing, is_owner=is_owner)
        raise HTTPException(status_code=409, detail="Payment has already been funded or closed.")

    if not intent.amount_ngn:
        raise HTTPException(status_code=400, detail="Payment intent has no NGN amount.")

    bank_account = await db.get(MerchantBankAccount, intent.bank_account_id)
    if not bank_account:
        raise HTTPException(status_code=404, detail="bank_account_not_found")

    service = PajCashService()
    try:
        resolved = await service.resolve_solana_token(req.token)
    except PajCashError as exc:
        _raise_paj_http_error(exc)

    existing_for_mint = (
        await db.execute(
            select(PajOfframpOrder)
            .where(
                PajOfframpOrder.payment_intent_id == intent.id,
                PajOfframpOrder.mint == resolved["mint"],
                PajOfframpOrder.status == PajOrderStatus.INIT.value,
            )
            .order_by(PajOfframpOrder.created_at.desc())
        )
    ).scalars().first()
    is_owner = current_user is not None and intent.user_id == current_user.id
    if existing_for_mint:
        existing_for_mint.updated_at = utc_now()
        db.add(existing_for_mint)
        await db.commit()
        await db.refresh(existing_for_mint)
        return format_paj_offramp(existing_for_mint, is_owner=is_owner)

    try:
        order = await service.create_offramp_order(
            db,
            user_id=intent.user_id,
            payment_intent_id=intent.id,
            bank_account_id=bank_account.id,
            bank_code=bank_account.bank_code,
            bank_name=bank_account.bank_name,
            account_number=bank_account.account_number,
            account_name=bank_account.account_name,
            mint=resolved["mint"],
            token_symbol=resolved["symbol"],
            token_decimals=resolved["decimals"],
            fiat_amount=intent.amount_ngn,
            narration=(intent.memo or intent.merchant_ref)[:100],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PajCashError as exc:
        _raise_paj_http_error(exc)
    await record_trace_event(
        db,
        source="paj",
        event_type="paj_order_created",
        summary=f"Created Paj Cash {resolved['symbol']} offramp order ({order.token_amount} {resolved['symbol']})",
        status="info",
        payment_intent_id=intent.id,
        paj_order_id=order.id,
        details={
            "pajOrderId": order.paj_order_id,
            "depositAddress": order.deposit_address,
            "token": resolved["symbol"],
            "tokenAmount": order.token_amount,
            "fiatAmount": order.fiat_amount,
        },
        commit=True,
    )
    return format_paj_offramp(order, is_owner=is_owner)


@router.post("/intents/{intent_id}/paj-offramp/reconcile")
async def reconcile_intent_paj_offramp(
    intent_id: str,
    req: Optional[ReconcilePajOfframpRequest] = Body(default=None),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    order: PajOfframpOrder | None = None
    if req and req.orderId is not None:
        order = await db.get(PajOfframpOrder, req.orderId)
        if not order or order.payment_intent_id != intent.id:
            raise HTTPException(status_code=404, detail="paj_offramp_not_found")
    else:
        order = await _latest_paj_offramp_for_intent(db, intent.id)
    if not order:
        raise HTTPException(status_code=404, detail="No Paj Cash offramp order exists for this payment.")

    try:
        updated = await PajCashService().reconcile_offramp_order(db, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PajCashError as exc:
        _raise_paj_http_error(exc)

    await mark_intent_funded_from_paj(db, updated)
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_paj_offramp(updated, is_owner=is_owner)


@router.post("/intents/{intent_id}/fiat-checkout")
async def create_intent_fiat_checkout(
    intent_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = (
        await db.execute(select(PaymentIntent).where(PaymentIntent.id == uuid_id))
    ).scalars().first()
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    expiry_utc = intent.expires_at.replace(tzinfo=timezone.utc) if intent.expires_at and intent.expires_at.tzinfo is None else intent.expires_at
    if intent.status == "created" and expiry_utc and datetime.now(timezone.utc) >= expiry_utc:
        intent.status = "failed"
        intent.failure_reason = "expired"
        intent.updated_at = utc_now()
        await db.commit()
        raise HTTPException(status_code=409, detail="This payment request has expired.")

    if intent.status != "created":
        existing = await _latest_checkout_for_intent(db, intent.id)
        if existing and existing.status == FiatPaymentStatus.COMPLETED.value:
            is_owner = current_user is not None and intent.user_id == current_user.id
            return format_fiat_payment(existing, is_owner=is_owner)
        raise HTTPException(status_code=409, detail="Payment has already been funded or closed.")

    existing = await _latest_checkout_for_intent(db, intent.id)
    if existing and existing.status in (
        FiatPaymentStatus.PENDING.value,
        FiatPaymentStatus.PROCESSING.value,
        FiatPaymentStatus.COMPLETED.value,
    ):
        is_owner = current_user is not None and intent.user_id == current_user.id
        return format_fiat_payment(existing, is_owner=is_owner)
    if not intent.allow_fiat_checkout or intent.receive_mode == "private":
        raise HTTPException(
            status_code=403,
            detail="Bank transfer is not enabled for this payment request.",
        )

    fiat_checkout = await _ensure_intent_fiat_checkout(db, intent)
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_fiat_payment(fiat_checkout, is_owner=is_owner)


@router.post("/intents/{intent_id}/reconcile")
async def reconcile_intent(
    intent_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    intent, fiat_checkout, paj_offramp, fiat_payout, bank_account = (
        await _reconcile_intent_all_rails(db, intent)
    )
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_intent(
        intent,
        is_owner=is_owner,
        fiat_checkout=fiat_checkout,
        paj_offramp=paj_offramp,
        bank_account=bank_account,
        fiat_payout=fiat_payout,
    )


async def _sync_fiat_checkout_against_intent(
    db: AsyncSession, intent: PaymentIntent, fiat_checkout: FiatPayment
) -> bool:
    """Reconcile Paj/on-chain rails for an intent and supersede unused FossaPay checkouts."""
    paj_orders = await _reconcile_intent_paj_orders(db, intent)
    refreshed = await db.get(PaymentIntent, intent.id)
    if refreshed is not None:
        intent = refreshed
    expired_candidate = intent.status == "failed" and intent.failure_reason == "expired"
    if (intent.status == "created" or expired_candidate) and intent.receive_mode != "private":
        await _find_matching_onchain_transfer(db, intent, paj_orders)
        refreshed = await db.get(PaymentIntent, intent.id)
        if refreshed is not None:
            intent = refreshed
    if intent.status in ("funded", "claimed") and intent.paid_via in ("paj", "crypto"):
        await _mark_pending_fiat_checkout_superseded(db, intent.id, intent.paid_via)
        await db.commit()
        await db.refresh(fiat_checkout)
        return True
    return False


@router.post("/intents/{intent_id}/fiat-checkout/reconcile")
async def reconcile_intent_fiat_checkout(
    intent_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = (
        await db.execute(select(PaymentIntent).where(PaymentIntent.id == uuid_id))
    ).scalars().first()
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    fiat_checkout = await _latest_checkout_for_intent(db, intent.id)
    if not fiat_checkout:
        raise HTTPException(status_code=404, detail="No bank transfer checkout exists for this payment.")

    is_owner = current_user is not None and intent.user_id == current_user.id
    if await _sync_fiat_checkout_against_intent(db, intent, fiat_checkout):
        return format_fiat_payment(fiat_checkout, is_owner=is_owner)

    try:
        updated = await FossaPayService().reconcile_checkout(db, fiat_checkout)
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)

    await mark_intent_funded_from_fiat(db, updated)
    return format_fiat_payment(updated, is_owner=is_owner)

@router.post("/intents/{intent_id}/confirm-fund")
async def confirm_fund(
    intent_id: str,
    req: ConfirmFundRequest,
    db: AsyncSession = Depends(get_session)
    # Note: A customer might call this, so we don't strictly require `current_user` to be the merchant here.
):
    uuid_id = parse_uuid(intent_id)
    stmt = (
        select(PaymentIntent)
        .where(PaymentIntent.id == uuid_id)
        .with_for_update()
    )
    res = await db.execute(stmt)
    intent = res.scalars().first()

    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    expired_candidate = intent.status == "failed" and intent.failure_reason == "expired"
    if intent.status != "created" and not expired_candidate:
        raise HTTPException(status_code=409, detail="Payment has already been funded or claimed.")

    expiry_utc = intent.expires_at.replace(tzinfo=timezone.utc) if intent.expires_at and intent.expires_at.tzinfo is None else intent.expires_at

    duplicate = await db.execute(
        select(PaymentIntent.id).where(
            PaymentIntent.fund_signature == req.signature
        )
    )
    if duplicate.first():
        raise HTTPException(status_code=409, detail="Signature already used")

    verify_mint = intent.mint
    verify_address = intent.recipient_address
    verify_atomic = intent.amount_atomic
    offramp_order: PajOfframpOrder | None = None

    if req.pajOfframpOrderId is not None:
        if intent.receive_mode == "private":
            raise HTTPException(
                status_code=400,
                detail="Private Umbra payments cannot use a Paj Cash offramp order.",
            )
        offramp_order = await db.get(PajOfframpOrder, req.pajOfframpOrderId)
        if not offramp_order or offramp_order.payment_intent_id != intent.id:
            raise HTTPException(status_code=404, detail="paj_offramp_not_found")
        if not offramp_order.token_amount:
            raise HTTPException(status_code=400, detail="Offramp order is missing token amount.")
        verify_mint = offramp_order.mint
        verify_address = offramp_order.deposit_address
        verify_atomic = str(
            int((Decimal(offramp_order.token_amount) * (Decimal(10) ** offramp_order.token_decimals)).to_integral_value(rounding=ROUND_DOWN))
        )

    if intent.receive_mode == "private":
        is_valid_tx = await verify_umbra_deposit(
            req.signature,
            verify_mint,
            verify_atomic,
            intent.created_at,
            before=intent.expires_at,
        )
    else:
        is_valid_tx = await verify_transfer(
            req.signature,
            verify_mint,
            verify_address,
            verify_atomic,
            intent.created_at,
            expected_memo=f"veil:{intent.id}",
            before=intent.expires_at,
        )
    if not is_valid_tx:
        if expiry_utc and datetime.now(timezone.utc) >= expiry_utc:
            intent.status = "failed"
            intent.failure_reason = "expired"
            intent.updated_at = utc_now()
            await db.commit()
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    paid_via = "paj" if offramp_order is not None else "crypto"
    if offramp_order is not None:
        offramp_order.tx_signature = req.signature
        if offramp_order.status == PajOrderStatus.INIT.value:
            offramp_order.status = PajOrderStatus.PROCESSING.value
        offramp_order.updated_at = utc_now()
        db.add(offramp_order)

    intent.status = "funded"
    intent.failure_reason = None
    intent.fund_signature = req.signature
    intent.paid_via = paid_via
    intent.updated_at = utc_now()
    await _mark_pending_fiat_checkout_superseded(db, intent.id, paid_via)
    direct_crypto_on_fiat = intent.settlement_target == SettlementTarget.FIAT.value and offramp_order is None
    await record_trace_event(
        db,
        source="solana",
        event_type="direct_crypto_on_fiat_intent" if direct_crypto_on_fiat else "fund_confirmed",
        summary=(
            f"Direct on-chain transfer {req.signature[:12]}... landed on a fiat-settled request"
            if direct_crypto_on_fiat
            else f"Verified on-chain funding {req.signature[:12]}... via {paid_via}"
        ),
        status="warn" if direct_crypto_on_fiat else "ok",
        payment_intent_id=intent.id,
        paj_order_id=offramp_order.id if offramp_order is not None else None,
        details={
            "signature": req.signature,
            "paidVia": paid_via,
            "recoveredFromExpired": expired_candidate,
            "settlementTarget": intent.settlement_target,
        },
    )

    db.add(intent)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Signature already used") from exc
    await db.refresh(intent)
    fiat_checkout = await _latest_checkout_for_intent(db, intent.id)
    bank_account = (
        await db.get(MerchantBankAccount, intent.bank_account_id)
        if intent.bank_account_id
        else None
    )
    return format_intent(
        intent,
        is_owner=False,
        fiat_checkout=fiat_checkout,
        paj_offramp=offramp_order,
        bank_account=bank_account,
    )

@router.post("/intents/{intent_id}/confirm-claim")
async def confirm_claim(
    intent_id: str,
    req: ConfirmClaimRequest,
    current_user: User = Depends(get_current_user), # must be logged in
    db: AsyncSession = Depends(get_session)
):
    uuid_id = parse_uuid(intent_id)
    stmt = (
        select(PaymentIntent)
        .where(PaymentIntent.id == uuid_id)
        .with_for_update()
    )
    res = await db.execute(stmt)
    intent = res.scalars().first()

    if not intent or intent.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="intent_not_found")


    if intent.status != "funded":
        raise HTTPException(status_code=409, detail="Can only claim a funded payment.")

    if intent.receive_mode != "private":
        raise HTTPException(
            status_code=409,
            detail="Public payments are settled once funded.",
        )

    duplicate = await db.execute(
        select(PaymentIntent.id).where(
            PaymentIntent.claim_signature == req.signature
        )
    )
    if duplicate.first():
        raise HTTPException(status_code=409, detail="Signature already used")

    if not await verify_transfer(
        req.signature,
        intent.mint,
        intent.recipient_address,
        intent.amount_atomic,
        intent.updated_at,
        direction="out",
    ):
        raise HTTPException(
            status_code=400,
            detail="Claim transaction not verified on-chain.",
        )

    intent.status = "claimed"
    intent.claim_signature = req.signature
    intent.paid_via = intent.paid_via or "crypto"
    intent.updated_at = utc_now()
    await record_trace_event(
        db,
        source="solana",
        event_type="claim_confirmed",
        summary=f"Private Umbra claim confirmed ({req.signature[:12]}...)",
        status="ok",
        payment_intent_id=intent.id,
        actor_address=current_user.address,
        details={"claimSignature": req.signature},
    )

    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent, is_owner=True)


@router.get("/fiat")
async def list_fiat_payments(
    flow: Optional[Literal["checkout", "payout"]] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    stmt = select(FiatPayment).where(FiatPayment.user_id == current_user.id)
    if flow is not None:
        stmt = stmt.where(FiatPayment.flow == flow)
    stmt = stmt.order_by(FiatPayment.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [format_fiat_payment(row, is_owner=True) for row in rows]


@router.get("/fiat/banks")
async def list_fiat_banks(
    current_user: User = Depends(get_current_user),
):
    global _BANKS_CACHE
    now = time.monotonic()
    if _BANKS_CACHE is not None and now - _BANKS_CACHE[0] < _BANKS_CACHE_TTL_SECONDS:
        return _BANKS_CACHE[1]
    try:
        banks = await FossaPayService().get_supported_banks()
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)
    _BANKS_CACHE = (now, banks)
    return banks


@router.post("/fiat/bank-name-enquiry")
async def fiat_bank_name_enquiry(
    req: BankNameEnquiryRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return await FossaPayService().verify_bank_account(
            bank_code=req.bankCode.strip(),
            account_number=req.accountNumber.strip(),
        )
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)


@router.get("/fiat/fee")
async def fiat_transfer_fee(
    amount: Decimal = Query(gt=0),
    current_user: User = Depends(get_current_user),
):
    try:
        return await FossaPayService().calculate_transfer_fee(amount_ngn=amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)


@router.post("/fiat/checkouts")
async def create_fiat_checkout(
    req: CreateFiatCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if req.paymentIntentId is not None:
        intent = await db.get(PaymentIntent, req.paymentIntentId)
        if not intent or intent.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="intent_not_found")

    reference = req.reference or f"CHK-{uuid4().hex[:16]}"
    try:
        payment = await FossaPayService().create_checkout(
            db,
            user_id=current_user.id,
            payment_intent_id=req.paymentIntentId,
            amount_ngn=req.amount_ngn,
            reference=reference,
            fee_bearer=req.feeBearer,
            description=req.description,
            idempotency_key=req.idempotencyKey,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)
    return format_fiat_payment(payment, is_owner=True)


@router.post("/fiat/payouts")
async def create_fiat_payout(
    req: CreateFiatPayoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if req.paymentIntentId is not None:
        intent = await db.get(PaymentIntent, req.paymentIntentId)
        if not intent or intent.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="intent_not_found")

    reference = req.reference or f"PAYOUT-{uuid4().hex[:14]}"
    try:
        payment = await FossaPayService().create_payout(
            db,
            user_id=current_user.id,
            payment_intent_id=req.paymentIntentId,
            amount_ngn=req.amount_ngn,
            reference=reference,
            bank_code=req.bankCode.strip(),
            bank_name=req.bankName.strip(),
            account_name=req.accountName.strip(),
            account_number=req.accountNumber.strip(),
            remarks=req.remarks,
            idempotency_key=req.idempotencyKey,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)
    return format_fiat_payment(payment, is_owner=True)


@router.get("/fiat/{fiat_id}")
async def get_fiat_payment(
    fiat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(fiat_id)
    payment = await db.get(FiatPayment, uuid_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="fiat_payment_not_found")
    return format_fiat_payment(payment, is_owner=True)


@router.post("/fiat/{fiat_id}/reconcile")
async def reconcile_fiat_payment(
    fiat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(fiat_id)
    payment = await db.get(FiatPayment, uuid_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="fiat_payment_not_found")

    service = FossaPayService()
    try:
        if payment.flow == FiatPaymentFlow.CHECKOUT.value:
            if payment.payment_intent_id is not None:
                linked_intent = await db.get(PaymentIntent, payment.payment_intent_id)
                if linked_intent is not None and await _sync_fiat_checkout_against_intent(
                    db, linked_intent, payment
                ):
                    return format_fiat_payment(payment, is_owner=True)

            updated = await service.reconcile_checkout(db, payment)
            await mark_intent_funded_from_fiat(db, updated)
        else:
            updated = await service.reconcile_payout(db, payment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)
    return format_fiat_payment(updated, is_owner=True)


@router.post("/fiat/{fiat_id}/expire")
async def expire_fiat_payment(
    fiat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(fiat_id)
    payment = await db.get(FiatPayment, uuid_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="fiat_payment_not_found")
    if payment.flow != FiatPaymentFlow.CHECKOUT.value:
        raise HTTPException(status_code=409, detail="Only pending checkouts can be expired.")

    try:
        updated = await FossaPayService().expire_checkout(db, payment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FossaPayError as exc:
        if payment.status == FiatPaymentStatus.COMPLETED.value:
            await mark_intent_funded_from_fiat(db, payment)
        _raise_fossapay_http_error(exc)
    return format_fiat_payment(updated, is_owner=True)


@router.get("/paj/banks")
async def list_paj_banks(
    current_user: User = Depends(get_current_user),
):
    global _PAJ_BANKS_CACHE
    now = time.monotonic()
    if _PAJ_BANKS_CACHE is not None and now - _PAJ_BANKS_CACHE[0] < _BANKS_CACHE_TTL_SECONDS:
        return _PAJ_BANKS_CACHE[1]
    try:
        banks = await PajCashService().get_banks()
    except PajCashError as exc:
        _raise_paj_http_error(exc)
    _PAJ_BANKS_CACHE = (now, banks)
    return banks


@router.get("/paj/rates")
async def get_paj_rates():
    try:
        rates = await PajCashService().get_rates("NGN")
    except PajCashError as exc:
        _raise_paj_http_error(exc)
    return {
        **rates,
        "tokens": list(PAJ_SOLANA_TOKENS.values()),
    }


@router.get("/paj/bank-accounts")
async def list_paj_bank_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    stmt = (
        select(MerchantBankAccount)
        .where(MerchantBankAccount.user_id == current_user.id)
        .order_by(MerchantBankAccount.is_default.desc(), MerchantBankAccount.created_at.desc())
    )
    accounts = (await db.execute(stmt)).scalars().all()
    return [format_bank_account(acc, is_owner=True) for acc in accounts]


@router.post("/paj/bank-accounts")
async def register_paj_bank_account(
    req: RegisterPajBankAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        account = await PajCashService().register_bank_account(
            db,
            user_id=current_user.id,
            bank_code=req.bankCode.strip(),
            account_number=req.accountNumber.strip(),
            make_default=req.makeDefault,
        )
    except PajCashError as exc:
        _raise_paj_http_error(exc)
    return format_bank_account(account, is_owner=True)


@router.delete("/paj/bank-accounts/{account_id}")
async def delete_paj_bank_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(account_id)
    account = await db.get(MerchantBankAccount, uuid_id)
    if not account or account.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="bank_account_not_found")
    referenced_intent = (
        await db.execute(
            select(PaymentIntent.id).where(PaymentIntent.bank_account_id == account.id).limit(1)
        )
    ).first()
    referenced_order = (
        await db.execute(
            select(PajOfframpOrder.id).where(PajOfframpOrder.bank_account_id == account.id).limit(1)
        )
    ).first()
    if referenced_intent or referenced_order:
        raise HTTPException(
            status_code=409,
            detail="Bank account is linked to existing payments; add and set a different default bank account instead.",
        )
    await db.delete(account)
    await db.commit()
    return {"ok": True}


@router.get("/paj/offramps")
async def list_paj_offramps(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    stmt = (
        select(PajOfframpOrder)
        .where(PajOfframpOrder.user_id == current_user.id)
        .order_by(PajOfframpOrder.created_at.desc())
        .limit(limit)
    )
    orders = (await db.execute(stmt)).scalars().all()
    return [format_paj_offramp(order, is_owner=True) for order in orders]


@router.post("/paj/offramps/{order_id}/reconcile")
async def reconcile_paj_offramp(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(order_id)
    order = await db.get(PajOfframpOrder, uuid_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="paj_offramp_not_found")
    try:
        updated = await PajCashService().reconcile_offramp_order(db, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PajCashError as exc:
        _raise_paj_http_error(exc)
    await mark_intent_funded_from_paj(db, updated)
    return format_paj_offramp(updated, is_owner=True)
