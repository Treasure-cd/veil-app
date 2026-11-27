import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.merchant import Merchant
from app.models.user import User
from app.models.whatsapp import (
    WhatsAppLink,
    WhatsAppLinkCode,
    WhatsAppSession,
    WhatsAppSetupToken,
)
from core.config import settings


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
GRAPH_API_VERSION = "v26.0"
_PHONE_CACHE_TTL_SECONDS = 3600
_graph_phone_cache: dict[tuple[str, str], tuple[str, float]] = {}


def _digits_only(value: str | None) -> str:
    return "".join(character for character in (value or "") if character.isdigit())


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def format_whatsapp_url(digits: str, text: str = "") -> str:
    url = f"https://wa.me/{digits}"
    return f"{url}?text={quote(text, safe='')}" if text else url


async def resolve_business_phone_digits() -> str | None:
    configured = _digits_only(settings.WHATSAPP_BUSINESS_PHONE_NUMBER)
    if configured:
        return configured

    phone_number_id = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
    access_token = (settings.WHATSAPP_ACCESS_TOKEN or "").strip()
    if not phone_number_id or not access_token:
        return None

    cache_key = (phone_number_id, access_token)
    cached = _graph_phone_cache.get(cache_key)
    now_mono = time.monotonic()
    if cached and cached[1] > now_mono:
        return cached[0]

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                params={"fields": "display_phone_number"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not fetch WhatsApp display phone number from Meta Graph API: {}", exc)
        return None

    digits = _digits_only(payload.get("display_phone_number") if isinstance(payload, dict) else None)
    if not digits:
        return None

    _graph_phone_cache[cache_key] = (digits, now_mono + _PHONE_CACHE_TTL_SECONDS)
    return digits


async def whatsapp_url(text: str) -> str:
    digits = await resolve_business_phone_digits()
    if not digits:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp business phone number is not configured",
        )
    return format_whatsapp_url(digits, text)


async def join_url() -> str:
    return await whatsapp_url("")


async def create_link_code(db: AsyncSession, merchant_id: UUID) -> tuple[str, datetime]:
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


async def _link_phone_to_merchant(
    db: AsyncSession,
    *,
    merchant: User,
    phone_e164: str,
    source: str,
    now: datetime,
) -> str:
    link = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.phone_e164 == phone_e164)
        .with_for_update()
    )).scalars().first()
    if link:
        link.merchant_id = merchant.id
        link.source = source
        link.linked_at = now
    else:
        db.add(WhatsAppLink(
            merchant_id=merchant.id,
            phone_e164=phone_e164,
            source=source,
            linked_at=now,
        ))
    await db.execute(delete(WhatsAppSession).where(WhatsAppSession.phone_e164 == phone_e164))
    await db.execute(
        update(WhatsAppSetupToken)
        .where(
            WhatsAppSetupToken.phone_e164 == phone_e164,
            WhatsAppSetupToken.used_at.is_(None),
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )

    profile = (await db.execute(
        select(Merchant).where(Merchant.wallet_address == merchant.address)
    )).scalars().first()
    return (
        profile.business_name
        if profile and profile.business_name
        else f"{merchant.address[:4]}…{merchant.address[-4:]}"
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
    expires_at = _aware_utc(code.expires_at)
    if code.used_at is not None:
        return "used", ""
    if expires_at <= now:
        return "expired", ""

    merchant = await db.get(User, code.merchant_id)
    if not merchant:
        return "invalid", ""

    display_name = await _link_phone_to_merchant(
        db,
        merchant=merchant,
        phone_e164=phone_e164,
        source="code",
        now=now,
    )
    code.used_at = now
    await db.commit()
    return "linked", display_name


async def create_setup_token(db: AsyncSession, phone_e164: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    for _ in range(5):
        token = secrets.token_urlsafe(18)
        db.add(WhatsAppSetupToken(token=token, phone_e164=phone_e164, expires_at=expires_at))
        try:
            await db.commit()
            return token
        except IntegrityError:
            await db.rollback()
    raise RuntimeError("Could not create a WhatsApp setup token")


async def get_setup_token_preview(
    db: AsyncSession,
    *,
    token_value: str,
    merchant_id: UUID,
) -> tuple[str, dict | None]:
    setup = await db.get(WhatsAppSetupToken, token_value)
    if not setup:
        return "invalid", None
    now = datetime.now(timezone.utc)
    expires_at = _aware_utc(setup.expires_at)
    if setup.used_at is not None:
        return "used", None
    if expires_at <= now:
        return "expired", None

    existing = (await db.execute(
        select(WhatsAppLink).where(WhatsAppLink.phone_e164 == setup.phone_e164)
    )).scalars().first()
    return "ok", {
        "phone_masked": mask_phone(setup.phone_e164),
        "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "already_linked_to_current_user": bool(existing and existing.merchant_id == merchant_id),
        "already_linked_to_other_account": bool(existing and existing.merchant_id != merchant_id),
    }


async def consume_setup_token(
    db: AsyncSession,
    *,
    token_value: str,
    merchant_id: UUID,
) -> tuple[str, str, str]:
    setup = (await db.execute(
        select(WhatsAppSetupToken)
        .where(WhatsAppSetupToken.token == token_value)
        .with_for_update()
    )).scalars().first()
    if not setup:
        return "invalid", "", ""
    now = datetime.now(timezone.utc)
    expires_at = _aware_utc(setup.expires_at)
    if setup.used_at is not None:
        return "used", "", ""
    if expires_at <= now:
        return "expired", "", ""

    merchant = await db.get(User, merchant_id)
    if not merchant:
        return "invalid", "", ""

    display_name = await _link_phone_to_merchant(
        db,
        merchant=merchant,
        phone_e164=setup.phone_e164,
        source="setup_link",
        now=now,
    )
    setup.used_at = now
    await db.commit()
    return "linked", setup.phone_e164, display_name


def mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return "+" + "•" * max(1, len(phone) - 4) + phone[-4:]
    return f"{phone[:4]}{'•' * max(1, len(phone) - 8)}{phone[-4:]}"
