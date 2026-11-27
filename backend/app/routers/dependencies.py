from fastapi import Header, HTTPException, status, Depends
import jwt
from uuid import UUID
from core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from core.session import get_session
from app.models.user import User
from app.services.trace import SEED_ADMIN_ADDRESSES
from sqlmodel import select


async def ensure_seed_admin(db: AsyncSession, user: User) -> User:
    """Promote hardcoded seed admin wallets idempotently when encountered at runtime."""
    if user.address in SEED_ADMIN_ADDRESSES and not user.is_admin:
        user.is_admin = True
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session)
) -> User:

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token"
        )

    scheme, separator, token = authorization.partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
        or " " in token.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication header"
        )

    try:
        payload = jwt.decode(
            token.strip(),
            settings.JWT_SECRET,
            algorithms=["HS256"]
        )

        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )

        try:
            user_uuid = UUID(user_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user identifier"
            )

        stmt = select(User).where(User.id == user_uuid)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        return await ensure_seed_admin(db, user)

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )


async def get_optional_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> User | None:
    if not authorization:
        return None
    try:
        return await get_current_user(authorization=authorization, db=db)
    except HTTPException:
        return None


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user