from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional
from core.session import get_session
from app.routers.dependencies import get_current_user
from app.models.user import User
from app.models.payment import PaymentIntent

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)

class CreatePaymentIntentRequest(BaseModel):
    merchantRef: str
    mint: str
    amountAtomic: str
    recipientAddress: str
    receiveMode: str = "private"
    memo: Optional[str] = None

class ConfirmFundRequest(BaseModel):
    signature: str

class ConfirmClaimRequest(BaseModel):
    signature: str

def format_intent(intent: PaymentIntent) -> dict:
    return {
        "id": str(intent.id),
        "userId": str(intent.user_id),
        "merchantRef": intent.merchant_ref,
        "mint": intent.mint,
        "amountAtomic": intent.amount_atomic,
        "recipientAddress": intent.recipient_address,
        "receiveMode": intent.receive_mode,
        "memo": intent.memo,
        "status": intent.status,
        "createdAt": intent.created_at.isoformat() + "Z",
        "updatedAt": intent.updated_at.isoformat() + "Z",
        "fundSignature": intent.fund_signature,
        "claimSignature": intent.claim_signature,
        "failureReason": intent.failure_reason
    }

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
        status="created",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent)

@router.get("/intents/{intent_id}")
async def get_intent(
    intent_id: str,
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
    
    return format_intent(intent)

@router.post("/intents/{intent_id}/confirm-fund")
async def confirm_fund(
    intent_id: str,
    req: ConfirmFundRequest,
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

    intent.status = "funded"
    intent.fund_signature = req.signature
    intent.updated_at = datetime.utcnow()
    
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent)

@router.post("/intents/{intent_id}/confirm-claim")
async def confirm_claim(
    intent_id: str,
    req: ConfirmClaimRequest,
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

    intent.status = "claimed"
    intent.claim_signature = req.signature
    intent.updated_at = datetime.utcnow()
    
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return format_intent(intent)
