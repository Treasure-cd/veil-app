from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import uuid4
from datetime import datetime, timedelta, timezone
import base58
import bcrypt
import nacl.signing
import jwt
from core.session import get_session
from core.config import settings
from app.models.user import User, utc_now
from app.routers.dependencies import ensure_seed_admin, get_current_user
from app.services.trace import SEED_ADMIN_ADDRESSES

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def serialize_auth_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "address": user.address,
        "email": user.email,
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

class RegisterEmailRequest(BaseModel):
    email: EmailStr
    password: str

class LoginEmailRequest(BaseModel):
    email: EmailStr
    password: str

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

    return {
        "token": token,
        "user": serialize_auth_user(user),
    }


@router.get("/me")
async def get_authenticated_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    synced = await ensure_seed_admin(db, current_user)
    return serialize_auth_user(synced)


@router.post("/register")
async def register_email(
    req: RegisterEmailRequest,
    db: AsyncSession = Depends(get_session),
):
    email_lower = req.email.lower().strip()
    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters.",
        )

    existing = (await db.execute(select(User).where(User.email == email_lower))).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please sign in.",
        )

    # Email users get a placeholder address (not a real Solana pubkey).
    placeholder_address = f"email:{uuid4().hex}"
    user = User(
        address=placeholder_address,
        email=email_lower,
        password_hash=_hash_password(req.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_jwt_token(str(user.id), user.address)
    return {
        "token": token,
        "user": serialize_auth_user(user),
    }


@router.post("/login-email")
async def login_email(
    req: LoginEmailRequest,
    db: AsyncSession = Depends(get_session),
):
    email_lower = req.email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email_lower))).scalars().first()

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not _verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user.updated_at = utc_now()
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_jwt_token(str(user.id), user.address)
    return {
        "token": token,
        "user": serialize_auth_user(user),
    }
