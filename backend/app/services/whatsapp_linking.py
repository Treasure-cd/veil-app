import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.merchant import Merchant
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppLinkCode, WhatsAppSession
from core.config import settings


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def whatsapp_url(text: str) -> str:
    business_phone = settings.WHATSAPP_BUSINESS_PHONE_NUMBER or ""
    digits = "".join(character for character in business_phone if character.isdigit())
    if not digits:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp business phone number is not configured",
        )
    url = f"https://wa.me/{digits}"
    return f"{url}?text={quote(text, safe='')}" if text else url


def join_url() -> str:
    return whatsapp_url("")


async def create_link_code(db: AsyncSession, merchant_id: UUID) -> tuple[str, datetime]:
    # Validate the business number before persisting a code that cannot be used.
    join_url()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    for _ in range(5):
        code = secrets.choice(CODE_LETTERS) + "".join(
            secrets.choice(CODE_ALPHABET) for _ in range(5)
        )
        db.add(WhatsAppLinkCode(code=code, merchant_id=merchant_id, expires_at=expires_at))
        try:
            await db.commit()
            return code, expires_at
        except IntegrityError:
            await db.rollback()
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not create a WhatsApp link code. Please try again.",
    )


async def consume_link_code(
    db: AsyncSession,
    *,
    code_value: str,
    phone_e164: str,
) -> tuple[str, str]:
    code = (await db.execute(
        select(WhatsAppLinkCode)
        .where(WhatsAppLinkCode.code == code_value.upper())
        .with_for_update()
    )).scalars().first()
    if not code:
        return "invalid", ""
    now = datetime.now(timezone.utc)
    expires_at = code.expires_at.replace(tzinfo=timezone.utc) if code.expires_at.tzinfo is None else code.expires_at
    if code.used_at is not None:
        return "used", ""
    if expires_at <= now:
        return "expired", ""

    merchant = await db.get(User, code.merchant_id)
    if not merchant:
        return "invalid", ""

    link = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.phone_e164 == phone_e164)
        .with_for_update()
    )).scalars().first()
    if link:
        link.merchant_id = merchant.id
        link.source = "code"
        link.linked_at = now
    else:
        db.add(WhatsAppLink(
            merchant_id=merchant.id,
            phone_e164=phone_e164,
            source="code",
            linked_at=now,
        ))
    await db.execute(delete(WhatsAppSession).where(WhatsAppSession.phone_e164 == phone_e164))
    code.used_at = now

    profile = (await db.execute(
        select(Merchant).where(Merchant.wallet_address == merchant.address)
    )).scalars().first()
    display_name = profile.business_name if profile and profile.business_name else f"{merchant.address[:4]}…{merchant.address[-4:]}"
    await db.commit()
    return "linked", display_name


def mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return "+" + "•" * max(1, len(phone) - 4) + phone[-4:]
    return f"{phone[:4]}{'•' * max(1, len(phone) - 8)}{phone[-4:]}"

