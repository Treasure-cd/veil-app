from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
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
from solders.transaction_status import TransactionConfirmationStatus

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

# 1. ADDED BASIC VALIDATION
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
    # 2. TRIM DATA FOR NON-OWNERS (Privacy)
    data = {
        "id": str(intent.id),
        "merchantRef": intent.merchant_ref,
        "mint": intent.mint,
        "amountAtomic": intent.amount_atomic,
        "recipientAddress": intent.recipient_address,
        "receiveMode": intent.receive_mode,
        "memo": intent.memo,
        "status": intent.status,
        "createdAt": intent.created_at.isoformat() + "Z",
    }
    # Only show these fields to the merchant who owns the intent
    if is_owner:
        data.update({
            "userId": str(intent.user_id),
            "updatedAt": intent.updated_at.isoformat() + "Z",
            "fundSignature": intent.fund_signature,
            "claimSignature": intent.claim_signature,
            "failureReason": intent.failure_reason
        })
    return data

async def verify_solana_transaction(signature_str: str) -> bool:
    """Verifies that a transaction was successful on the blockchain."""
    try:
        sig = Signature.from_string(signature_str)
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            response = await client.get_signature_statuses(
                [sig],
                search_transaction_history=True,
            )
            if not response.value or not response.value[0]:
                return False
            transaction_status = response.value[0]
            return (
                transaction_status.err is None
                and transaction_status.confirmation_status
                in (
                    TransactionConfirmationStatus.Confirmed,
                    TransactionConfirmationStatus.Finalized,
                )
            )
    except Exception:
        return False

async def verify_transfer(
    signature_str: str,
    mint: str,
    address: str,
    amount_atomic: str,
    after: datetime,
    direction: Literal["in", "out"] = "in",
) -> bool:
    try:
        sig = Signature.from_string(signature_str)
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            response = await client.get_transaction(
                sig,
                encoding="jsonParsed",
                commitment=Confirmed,
                max_supported_transaction_version=0,
            )
        tx = response.value
        if tx is None or tx.transaction.meta is None:
            return False
        meta = tx.transaction.meta
        if meta.err is not None:
            return False

        after_utc = (
            after.replace(tzinfo=timezone.utc)
            if after.tzinfo is None
            else after.astimezone(timezone.utc)
        )
        created_ts = after_utc.timestamp()
        if tx.block_time is None or tx.block_time < created_ts:
            return False

        def balance(entries) -> int:
            total = 0
            for entry in entries or []:
                if str(entry.mint) == mint and str(entry.owner) == address:
                    total += int(entry.ui_token_amount.amount)
            return total

        delta = balance(meta.post_token_balances) - balance(meta.pre_token_balances)
        return delta >= int(amount_atomic) if direction == "in" else -delta >= int(amount_atomic)
    except Exception:
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

    # Check if the person viewing is the merchant who created it
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

    # 3. STATE MACHINE CHECK
    if intent.status != "created":
        raise HTTPException(status_code=409, detail="Payment has already been funded or claimed.")

    duplicate = await db.execute(
        select(PaymentIntent.id).where(
            PaymentIntent.fund_signature == req.signature
        )
    )
    if duplicate.first():
        raise HTTPException(status_code=409, detail="Signature already used")

    # 4. BLOCKCHAIN VERIFICATION
    is_valid_tx = await verify_transfer(
        req.signature,
        intent.mint,
        intent.recipient_address,
        intent.amount_atomic,
        intent.created_at,
    )
    if not is_valid_tx:
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    intent.status = "funded"
    intent.fund_signature = req.signature
    intent.updated_at = utc_now()

    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent, is_owner=False)

@router.post("/intents/{intent_id}/confirm-claim")
async def confirm_claim(
    intent_id: str,
    req: ConfirmClaimRequest,
    current_user: User = Depends(get_current_user), # MUST BE LOGGED IN
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

    # 5. OWNERSHIP CHECK: Only the merchant can claim
    if not intent or intent.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="intent_not_found")

    # 6. STATE MACHINE CHECK: Can only claim if it's currently funded
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
