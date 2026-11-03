from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional, Literal
from core.session import get_session
from app.routers.dependencies import get_current_user
from app.models.user import User
from app.models.payment import PaymentIntent
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

SOLANA_RPC_URL = "https://api.devnet.solana.com"

# 1. ADDED BASIC VALIDATION
class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    mint: str
    amountAtomic: str
    recipientAddress: str
    receiveMode: Literal["private", "public"] = "private"
    memo: Optional[str] = None

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
        async with AsyncClient(SOLANA_RPC_URL) as client:
            response = await client.get_signature_statuses([sig])
            if not response.value or not response.value[0]: return False
            return response.value[0].err is None
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
    current_user: Optional[User] = Depends(get_current_user), # Can be called by anyone (e.g., a customer viewing a checkout page)
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(intent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid intent ID")

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
    uuid_id = UUID(intent_id)
    stmt = select(PaymentIntent).where(PaymentIntent.id == uuid_id)
    res = await db.execute(stmt)
    intent = res.scalars().first()

    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    # 3. STATE MACHINE CHECK
    if intent.status != "created":
        raise HTTPException(status_code=409, detail="Payment has already been funded or claimed.")

    # 4. BLOCKCHAIN VERIFICATION
    is_valid_tx = await verify_solana_transaction(req.signature)
    if not is_valid_tx:
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    intent.status = "funded"
    intent.fund_signature = req.signature
    intent.updated_at = datetime.now(timezone.utc)

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
    uuid_id = UUID(intent_id)
    stmt = select(PaymentIntent).where(PaymentIntent.id == uuid_id)
    res = await db.execute(stmt)
    intent = res.scalars().first()

    # 5. OWNERSHIP CHECK: Only the merchant can claim
    if not intent or intent.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="intent_not_found")

    # 6. STATE MACHINE CHECK: Can only claim if it's currently funded
    if intent.status != "funded":
        raise HTTPException(status_code=409, detail="Can only claim a funded payment.")

    intent.status = "claimed"
    intent.claim_signature = req.signature
    intent.updated_at = datetime.now(timezone.utc)

    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent, is_owner=True)
