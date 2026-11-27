import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.user import User
from app.models.whatsapp import WhatsAppLink
from app.services.phone_numbers import normalize_phone_number
from app.services.whatsapp_linking import join_url
from core.config import settings


_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT = 5
_RATE_WINDOW_SECONDS = 60


def check_rate_limit(ip_address: str, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    attempts = _requests_by_ip[ip_address]
    while attempts and current - attempts[0] >= _RATE_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many demo-link requests. Please try again in a minute.",
            headers={"Retry-After": "60"},
        )
    attempts.append(current)


def ensure_demo_enabled() -> None:
    """Gate the public demo on its feature flag; no user-supplied secret required."""
    if settings.WHATSAPP_DEMO_MODE != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo access is unavailable.",
        )


async def create_demo_link(
    db: AsyncSession,
    phone_value: str,
    merchant: User | None = None,
) -> str:
    """Link a phone to the demo bot.

    When `merchant` is supplied (the test user signed in with their own wallet),
    checkout links created by the bot pay that wallet. Otherwise the shared
    configured demo wallet is used, subject to the demo number cap.
    """
    try:
        phone = normalize_phone_number(phone_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Enter a valid phone number.") from exc
    destination = await join_url()

    personal_wallet = merchant is not None
    source = "demo_wallet" if personal_wallet else "demo"
    if not personal_wallet:
        wallet = settings.WHATSAPP_DEMO_MERCHANT_WALLET
        if not wallet:
            raise HTTPException(status_code=503, detail="Demo merchant wallet is not configured.")
        merchant = (await db.execute(select(User).where(User.address == wallet))).scalars().first()
        if not merchant:
            raise HTTPException(
                status_code=404,
                detail="No Veil merchant account exists for the configured demo wallet.",
            )

    # Serializing through the merchant row prevents concurrent requests from
    # racing on the shared demo cap and keeps repeated links idempotent.
    await db.execute(select(User.id).where(User.id == merchant.id).with_for_update())
    existing = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.phone_e164 == phone)
        .with_for_update()
    )).scalars().first()
    if existing and existing.source == source:
        existing.merchant_id = merchant.id
        existing.linked_at = datetime.now(timezone.utc)
        await db.commit()
        return destination

    # The cap only protects the shared demo wallet; a signed-in user brings
    # their own receiving wallet, so they don't consume the shared slots.
    if not personal_wallet:
        demo_count = (await db.execute(
            select(func.count(WhatsAppLink.id)).where(WhatsAppLink.source == "demo")
        )).scalar_one()
        if demo_count >= settings.WHATSAPP_DEMO_MAX_NUMBERS:
            raise HTTPException(
                status_code=409,
                detail="The WhatsApp demo has reached its number limit.",
            )

    now = datetime.now(timezone.utc)
    if existing:
        existing.merchant_id = merchant.id
        existing.source = source
        existing.linked_at = now
    else:
        db.add(WhatsAppLink(
            merchant_id=merchant.id,
            phone_e164=phone,
            source=source,
            linked_at=now,
        ))
    await db.commit()
    return destination
