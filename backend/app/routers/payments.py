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
    PaymentIntent,
    utc_now,
)
from app.models.user import User
from app.routers.dependencies import get_current_user, get_optional_user
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
_BANKS_CACHE_TTL_SECONDS = 3600

class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    token: Literal["USDC", "SOL"]
    amount_ngn: Decimal = Field(validation_alias=AliasChoices("amount_ngn", "amountNgn"))
    recipientAddress: str
    receiveMode: Literal["private", "public"] = "private"
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

class ConfirmClaimRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)


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

    intent = await create_payment_intent(
        db=db,
        user_id=current_user.id,
        recipient_address=req.recipientAddress,
        amount_ngn=req.amount_ngn,
        merchant_ref=req.merchantRef,
        token=req.token,
        memo=req.memo,
        source="web",
        receive_mode=req.receiveMode,
    )
    fiat_checkout: FiatPayment | None = None
    if req.includeFiatCheckout:
        fiat_checkout = await _ensure_intent_fiat_checkout(
            db, intent, fee_bearer=req.feeBearer
        )
    return format_intent(intent, is_owner=True, fiat_checkout=fiat_checkout)

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
    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_intent(intent, is_owner=is_owner, fiat_checkout=fiat_checkout)


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

    is_valid_tx = await verify_transfer(
        req.signature,
        intent.mint,
        intent.recipient_address,
        intent.amount_atomic,
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
    return format_intent(intent, is_owner=False)

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
