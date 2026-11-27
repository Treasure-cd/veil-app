from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppSession
from app.routers.dependencies import get_current_user, get_optional_user
from app.routers.whatsapp import MENU, _send_whatsapp
from app.services.phone_numbers import normalize_phone_number
from app.services.whatsapp_demo import check_rate_limit, create_demo_link, ensure_demo_enabled
from app.services.whatsapp_linking import (
    consume_setup_token,
    create_link_code,
    format_whatsapp_url,
    get_setup_token_preview,
    mask_phone,
    resolve_business_phone_digits,
)
from core.config import settings
from core.session import get_session

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class DemoLinkRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=64)


class CompleteSetupRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


def _raise_for_setup_token_status(token_status: str) -> None:
    if token_status == "used":
        raise HTTPException(
            status_code=410,
            detail="This WhatsApp setup link has already been used.",
        )
    if token_status == "expired":
        raise HTTPException(
            status_code=410,
            detail="This WhatsApp setup link has expired. Text the bot again for a new link.",
        )
    raise HTTPException(
        status_code=404,
        detail="Invalid WhatsApp setup link. Text the bot again for a new link.",
    )


@router.post("/link-code")
async def issue_link_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    code, expires_at = await create_link_code(db, current_user.id)
    digits = await resolve_business_phone_digits()
    return {
        "code": code,
        "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "join_url": format_whatsapp_url(digits) if digits else None,
        "link_url": format_whatsapp_url(digits, f"link {code}") if digits else None,
    }


@router.get("/setup/{token}")
async def preview_whatsapp_setup(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    token_status, preview = await get_setup_token_preview(
        db,
        token_value=token,
        merchant_id=current_user.id,
    )
    if token_status != "ok" or preview is None:
        _raise_for_setup_token_status(token_status)
    return preview


@router.post("/setup/complete")
async def complete_whatsapp_setup(
    payload: CompleteSetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    token_status, phone_e164, display_name = await consume_setup_token(
        db,
        token_value=payload.token,
        merchant_id=current_user.id,
    )
    if token_status != "linked":
        _raise_for_setup_token_status(token_status)

    notified = False
    if settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID:
        try:
            await _send_whatsapp(
                to_number=phone_e164,
                body=f"Your WhatsApp is now linked to {display_name}. {MENU}",
            )
            notified = True
        except Exception as exc:
            logger.warning("Failed to send WhatsApp link confirmation to {}: {}", phone_e164, exc)

    return {
        "ok": True,
        "phone_masked": mask_phone(phone_e164),
        "display_name": display_name,
        "notified_whatsapp": notified,
    }


@router.get("/status")
async def whatsapp_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    link = (await db.execute(
        select(WhatsAppLink)
        .where(WhatsAppLink.merchant_id == current_user.id)
        .order_by(WhatsAppLink.linked_at.desc())
        .limit(1)
    )).scalars().first()
    return {
        "linked": link is not None,
        "phone_masked": mask_phone(link.phone_e164) if link else None,
    }


@router.delete("/link")
async def unlink_whatsapp(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    links = (await db.execute(
        select(WhatsAppLink).where(WhatsAppLink.merchant_id == current_user.id)
    )).scalars().all()
    phones = [link.phone_e164 for link in links]
    if phones:
        await db.execute(delete(WhatsAppSession).where(WhatsAppSession.phone_e164.in_(phones)))
        for link in links:
            await db.delete(link)
        await db.commit()
    return {"ok": True}


@router.post("/demo-link")
async def demo_link(
    payload: DemoLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_optional_user),
):
    ip_address = request.client.host if request.client else "unknown"
    rate_limited = False
    try:
        check_rate_limit(ip_address)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        rate_limited = True
    ensure_demo_enabled()
    # Don't silently fall back to the shared demo wallet if the browser sent a
    # token we can't verify - that would send funds somewhere the user didn't pick.
    if request.headers.get("Authorization") and current_user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    if rate_limited:
        raise HTTPException(
            status_code=429,
            detail="Too many demo-link requests. Please try again in a minute.",
            headers={"Retry-After": "60"},
        )
    try:
        phone = normalize_phone_number(payload.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Enter a valid phone number.") from exc
    # A signed-in test user links their own wallet; otherwise fall back to the
    # shared demo merchant. Pass canonical E.164 so all entry points normalize alike.
    link_url = await create_demo_link(db, phone, merchant=current_user)
    return {"ok": True, "join_url": link_url}
