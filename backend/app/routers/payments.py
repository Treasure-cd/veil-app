import asyncio
import logging
import base58
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional, Literal
from core.config import settings
from core.session import get_session
from app.routers.dependencies import get_current_user, get_optional_user
from app.models.user import User
from app.models.payment import PaymentIntent, utc_now
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.signature import Signature

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

logger = logging.getLogger(__name__)

class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    mint: str
    amountAtomic: str
    recipientAddress: str
    receiveMode: Literal["private", "public"] = "private"
    memo: Optional[str] = None

    @field_validator("mint", "recipientAddress")
    @classmethod
    def validate_pubkey(cls, v: str):
        try:
            Pubkey.from_string(v)
        except ValueError as exc:
            raise ValueError("Invalid Solana address") from exc
        return v

    @field_validator("amountAtomic")
    @classmethod
    def validate_amount(cls, v: str):
        if not v.isdigit() or int(v) <= 0:
            raise ValueError("Amount must be a positive number")
        return v

class ConfirmFundRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)

class ConfirmClaimRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)

def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid intent ID") from exc

def format_intent(intent: PaymentIntent, is_owner: bool = True) -> dict:
    data = {
        "id": str(intent.id),
        "merchantRef": intent.merchant_ref,
        "mint": intent.mint,
        "amountAtomic": intent.amount_atomic,
        "recipientAddress": intent.recipient_address,
        "receiveMode": intent.receive_mode,
        "memo": intent.memo,
        "status": intent.status,
        # This signature is public on Solana and lets payers inspect the confirmed transfer.
        "fundSignature": intent.fund_signature,
        "createdAt": intent.created_at.isoformat() + "Z",
    }
    # Only show these fields to the merchant who owns the intent
    if is_owner:
        data.update({
            "userId": str(intent.user_id),
            "updatedAt": intent.updated_at.isoformat() + "Z",
            "claimSignature": intent.claim_signature,
            "failureReason": intent.failure_reason
        })
    return data

async def verify_transfer(
    signature_str: str,
    mint: str,
    address: str,
    amount_atomic: str,
    after: datetime,
    direction: Literal["in", "out"] = "in",
    expected_memo: str | None = None,
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

@router.post("/intents")
async def create_intent(
    req: CreatePaymentIntentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    intent = PaymentIntent(
        user_id=current_user.id,
        merchant_ref=req.merchantRef,
        mint=req.mint,
        amount_atomic=req.amountAtomic,
        recipient_address=req.recipientAddress,
        receive_mode=req.receiveMode,
        memo=req.memo,
        status="created"
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent, is_owner=True)

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

    is_owner = current_user is not None and intent.user_id == current_user.id
    return format_intent(intent, is_owner=is_owner)

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

    if intent.status != "created":
        raise HTTPException(status_code=409, detail="Payment has already been funded or claimed.")

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
    )
    if not is_valid_tx:
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    intent.status = "funded"
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
