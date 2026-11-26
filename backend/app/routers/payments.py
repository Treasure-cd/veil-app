import asyncio
import logging
import time
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from decimal import Decimal

import base58
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field, field_validator
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

class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    token: Literal["USDC", "SOL"]
    amount_ngn: Decimal = Field(validation_alias=AliasChoices("amount_ngn", "amountNgn"))
    recipientAddress: str
    receiveMode: Literal["private", "public"] = "private"
    settlementTarget: Literal["crypto", "fiat"] = "crypto"
    bankAccountId: Optional[UUID] = None
    memo: Optional[str] = None
    includeFiatCheckout: bool = False
    feeBearer: Literal["customer", "merchant"] = "customer"

    @field_validator("recipientAddress")
    @classmethod
    def validate_pubkey(cls, v: str):
        try:
            Pubkey.from_string(v)
        except ValueError as exc:
            raise ValueError("Invalid Solana address") from exc
        return v

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


async def _latest_paj_offramp_for_intent(
    db: AsyncSession, intent_id: UUID
) -> PajOfframpOrder | None:
    stmt = (
        select(PajOfframpOrder)
        .where(PajOfframpOrder.payment_intent_id == intent_id)
        .order_by(PajOfframpOrder.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


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
    if intent and (intent.status == "created" or expired_candidate):
        intent.status = "funded"
        intent.failure_reason = None
        if order.tx_signature and not intent.fund_signature:
            intent.fund_signature = order.tx_signature
        intent.updated_at = utc_now()
        db.add(intent)
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
        intent.updated_at = utc_now()
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
    return intent

def format_intent(
    intent: PaymentIntent,
    is_owner: bool = True,
    fiat_checkout: FiatPayment | None = None,
    paj_offramp: PajOfframpOrder | None = None,
    bank_account: MerchantBankAccount | None = None,
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
        "settlementTarget": intent.settlement_target,
        "memo": intent.memo,
        "status": intent.status,
        # This signature is public on Solana and lets payers inspect the confirmed transfer.
        "fundSignature": intent.fund_signature,
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
    }
    # Only show these fields to the merchant who owns the intent
    if is_owner:
        data.update({
            "userId": str(intent.user_id),
            "updatedAt": intent.updated_at.isoformat() + "Z",
            "claimSignature": intent.claim_signature,
            "failureReason": intent.failure_reason
        })
    data["amount_token"] = format(Decimal(intent.amount_atomic) / Decimal(10 ** (9 if intent.mint != settings.USDC_MINT else 6)), "f")
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
                    max_supported_transaction_version=0,
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
            instructions = tx.transaction.transaction.message.instructions
            memo_program = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

            def memo_matches(instruction) -> bool:
                if str(getattr(instruction, "program_id", "")) != memo_program:
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
            account_keys = tx.transaction.transaction.message.account_keys
            delta = 0
            for idx, key in enumerate(account_keys):
                pubkey_str = str(getattr(key, "pubkey", key))
                if pubkey_str == address:
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
        return await service.create_checkout(
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
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)


@router.post("/intents")
async def create_intent(
    req: CreatePaymentIntentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
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
        await db.commit()
        await db.refresh(intent)

    fiat_checkout = await _latest_checkout_for_intent(db, intent.id)
    paj_offramp = await _latest_paj_offramp_for_intent(db, intent.id)
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
    return format_paj_offramp(order, is_owner=is_owner)


@router.post("/intents/{intent_id}/paj-offramp/reconcile")
async def reconcile_intent_paj_offramp(
    intent_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

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

    fiat_checkout = await _ensure_intent_fiat_checkout(db, intent)
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_fiat_payment(fiat_checkout, is_owner=is_owner)


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

    try:
        updated = await FossaPayService().reconcile_checkout(db, fiat_checkout)
    except FossaPayError as exc:
        _raise_fossapay_http_error(exc)

    await mark_intent_funded_from_fiat(db, updated)
    is_owner = current_user is not None and intent.user_id == current_user.id
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
        offramp_order = await db.get(PajOfframpOrder, req.pajOfframpOrderId)
        if not offramp_order or offramp_order.payment_intent_id != intent.id:
            raise HTTPException(status_code=404, detail="paj_offramp_not_found")
        if not offramp_order.token_amount:
            raise HTTPException(status_code=400, detail="Offramp order is missing token amount.")
        verify_mint = offramp_order.mint
        verify_address = offramp_order.deposit_address
        verify_atomic = str(
            int((Decimal(offramp_order.token_amount) * (Decimal(10) ** offramp_order.token_decimals)).to_integral_value())
        )

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

    if offramp_order is not None:
        offramp_order.tx_signature = req.signature
        offramp_order.updated_at = utc_now()
        db.add(offramp_order)

    intent.status = "funded"
    intent.failure_reason = None
    intent.fund_signature = req.signature
    intent.updated_at = utc_now()

    db.add(intent)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Signature already used") from exc
    await db.refresh(intent)
    return format_intent(intent, is_owner=False, paj_offramp=offramp_order)

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
    intent.updated_at = utc_now()

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
