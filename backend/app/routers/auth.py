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
from app.models.whatsapp import WhatsAppLink
from app.routers.dependencies import ensure_seed_admin, get_current_user
from app.services.trace import SEED_ADMIN_ADDRESSES
from app.services.whatsapp_linking import (
    create_whatsapp_auth_challenge,
    format_whatsapp_url,
    mask_phone,
    poll_whatsapp_auth_challenge,
    resolve_business_phone_digits,
)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


def serialize_auth_user(user: User, *, phone_e164: str | None = None) -> dict:
    return {
        "id": str(user.id),
        "address": user.address,
        "hasWallet": not user.address.startswith("whatsapp:"),
        "phoneMasked": mask_phone(phone_e164) if phone_e164 else None,
        "isAdmin": bool(user.is_admin),
        "createdAt": user.created_at.isoformat() + "Z",
        "updatedAt": user.updated_at.isoformat() + "Z",
    }

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
            nonce_expires_at=expiry,
            is_admin=req.address in SEED_ADMIN_ADDRESSES,
            # created_at and updated_at are handled by SQLModel defaults
        )
        db.add(user)
    else:
        user.nonce = nonce
        user.nonce_expires_at = expiry
        if req.address in SEED_ADMIN_ADDRESSES:
            user.is_admin = True
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
    if user.address in SEED_ADMIN_ADDRESSES:
        user.is_admin = True
    user.updated_at = utc_now()
    db.add(user)
    await db.commit()
    await db.refresh(user)

    link = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.merchant_id == user.id)
        .order_by(WhatsAppLink.linked_at.desc())
        .limit(1)
    )).scalars().first()

    return {
        "token": token,
        "user": serialize_auth_user(user, phone_e164=link.phone_e164 if link else None),
    }


@router.get("/me")
async def get_authenticated_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    synced = await ensure_seed_admin(db, current_user)
    link = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.merchant_id == synced.id)
        .order_by(WhatsAppLink.linked_at.desc())
        .limit(1)
    )).scalars().first()
    return serialize_auth_user(synced, phone_e164=link.phone_e164 if link else None)


@router.post("/whatsapp/challenge")
async def start_whatsapp_auth(
    db: AsyncSession = Depends(get_session),
):
    token, code, expires_at = await create_whatsapp_auth_challenge(db)
    digits = await resolve_business_phone_digits()
    return {
        "challengeToken": token,
        "code": code,
        "expiresAt": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "joinUrl": format_whatsapp_url(digits) if digits else None,
        "sendUrl": format_whatsapp_url(digits, f"login {code}") if digits else None,
    }


@router.get("/whatsapp/poll/{token}")
async def poll_whatsapp_auth(
    token: str,
    db: AsyncSession = Depends(get_session),
):
    auth_status, user, phone_e164 = await poll_whatsapp_auth_challenge(
        db, token_value=token
    )
    if auth_status == "pending":
        return {"status": "pending"}
    if auth_status == "verified" and user is not None:
        synced = await ensure_seed_admin(db, user)
        jwt_token = create_jwt_token(str(synced.id), synced.address)
        return {
            "status": "verified",
            "token": jwt_token,
            "user": serialize_auth_user(synced, phone_e164=phone_e164),
        }
    if auth_status == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This WhatsApp sign-in code has expired. Generate a new code.",
        )
    if auth_status == "consumed":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This WhatsApp sign-in code has already been used.",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Invalid WhatsApp sign-in session.",
    )
