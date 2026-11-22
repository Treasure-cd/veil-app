from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppSession
from app.routers.dependencies import get_current_user
from app.services.phone_numbers import normalize_phone_number
from app.services.whatsapp_demo import check_rate_limit, create_demo_link, validate_demo_passcode
from app.services.whatsapp_linking import create_link_code, join_url, mask_phone, whatsapp_url
from core.session import get_session

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class DemoLinkRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=64)
    passcode: str = Field(max_length=256)


@router.post("/link-code")
async def issue_link_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    code, expires_at = await create_link_code(db, current_user.id)
    return {
        "code": code,
        "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "join_url": join_url(),
        "link_url": whatsapp_url(f"link {code}"),
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
):
    ip_address = request.client.host if request.client else "unknown"
    rate_limited = False
    try:
        check_rate_limit(ip_address)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        rate_limited = True
    validate_demo_passcode(payload.passcode)
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
    # Pass the canonical E.164 form into the service so all entry points share normalization.
    link_url = await create_demo_link(db, phone)
    return {"ok": True, "join_url": link_url}
