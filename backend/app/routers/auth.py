from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import uuid4
from datetime import datetime, timedelta, timezone
import base58
import nacl.signing
import jwt
from core.session import get_session
from core.config import settings
from app.models.user import User, utc_now

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

class ChallengeRequest(BaseModel):
    address: str

class ChallengeResponse(BaseModel):
    nonce: str

class LoginRequest(BaseModel):
    address: str
    signature: str
    message: str

def verify_solana_signature(public_key_b58: str, signature_b58: str, message: str) -> bool:
    try:
        pub_key_bytes = base58.b58decode(public_key_b58)
        sig_bytes = base58.b58decode(signature_b58)
        verify_key = nacl.signing.VerifyKey(pub_key_bytes)
        verify_key.verify(message.encode("utf-8"), sig_bytes)
        return True
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return False

def create_jwt_token(user_id: str, address: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "address": address,
        "exp": int((now + timedelta(days=7)).timestamp()),
        "iat": int(now.timestamp())
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

@router.post("/challenge", response_model=ChallengeResponse)
async def request_challenge(
    req: ChallengeRequest,
    db: AsyncSession = Depends(get_session)
):
    stmt = select(User).where(User.address == req.address)
    res = await db.execute(stmt)
    user = res.scalars().first()

    nonce = str(uuid4())
    expiry = utc_now() + timedelta(minutes=5)

    if not user:
        user = User(
            address=req.address,
            nonce=nonce,
            nonce_expires_at=expiry
            # created_at and updated_at are handled by SQLModel defaults
        )
        db.add(user)
    else:
        user.nonce = nonce
        user.nonce_expires_at = expiry
        user.updated_at = utc_now()
        db.add(user)

    await db.commit()
    return ChallengeResponse(nonce=nonce)

@router.post("/login")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_session)
):
    stmt = select(User).where(User.address == req.address)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user or not user.nonce or not user.nonce_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge not initiated"
        )

    now = utc_now()
    if now > user.nonce_expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication challenge expired. Request a new one."
        )

    expected_message = f"Sign this message to login to Veil: {user.nonce}"
    if req.message != expected_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message mismatch"
        )

    is_valid = verify_solana_signature(req.address, req.signature, req.message)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

    token = create_jwt_token(str(user.id), user.address)

    # Clear nonce on successful login
    user.nonce = None
    user.nonce_expires_at = None
    user.updated_at = utc_now()
    db.add(user)
    await db.commit()

    return {
        "token": token,
        "user": {
            "id": str(user.id),
            "address": user.address,
            "createdAt": user.created_at.isoformat() + "Z",
            "updatedAt": user.updated_at.isoformat() + "Z"
        }
    }
