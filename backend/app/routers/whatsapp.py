import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from app.models.payment import PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppMessage, WhatsAppSession
from app.services.payment_intents import create_payment_intent
from app.services.phone_numbers import normalize_phone_number
from app.services.whatsapp_parser import parse_message
from app.services.whatsapp_linking import consume_link_code
from core.config import settings
from core.session import get_session

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
logger = logging.getLogger(__name__)

MENU = "I can help with payments. Try: `link 5000 for lunch`, `recent`, or `help`."
APOLOGY = "Sorry, Veil couldn't process that just now. Please try again shortly."


def _twiml(message: str | None = None, status_code: int = 200) -> Response:
    response = MessagingResponse()
    if message:
        response.message(message)
    return Response(content=str(response), status_code=status_code, media_type="application/xml")


def _format_ngn(value: Decimal | str | None) -> str:
    amount = Decimal(str(value or 0))
    rounded = amount.quantize(Decimal("1")) if amount == amount.to_integral() else amount.normalize()
    return f"₦{rounded:,.2f}" if rounded != rounded.to_integral() else f"₦{rounded:,.0f}"


def _time_ago(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    seconds = max(0, int((datetime.now(timezone.utc) - aware).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _token_details(intent: PaymentIntent) -> tuple[str, Decimal]:
    token = "USDC" if intent.mint == settings.USDC_MINT else "SOL"
    decimals = 6 if token == "USDC" else 9
    amount = Decimal(intent.amount_atomic) / (Decimal(10) ** decimals)
    return token, amount


async def _recent_payments(db: AsyncSession, merchant_id: UUID) -> str:
    rows = (await db.execute(
        select(PaymentIntent)
        .where(PaymentIntent.user_id == merchant_id)
        .order_by(PaymentIntent.created_at.desc())
        .limit(5)
    )).scalars().all()
    if not rows:
        return "No payments yet. Share a checkout link to get started."

    lines = []
    paid_total = Decimal(0)
    for payment in rows:
        amount = Decimal(payment.amount_ngn or "0")
        if payment.status in ("funded", "claimed"):
            paid_total += amount
        label = payment.memo or payment.merchant_ref or "Payment"
        label = re.sub(r"\s+", " ", label).strip()[:45]
        lines.append(f"{_format_ngn(amount)} · {label} · {payment.status} · {_time_ago(payment.created_at)}")
    lines.append(f"Paid total: {_format_ngn(paid_total)}")
    return "Recent payments:\n" + "\n".join(lines)


@router.post("/webhook")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_session)):
    """Receive Twilio Sandbox messages and return a single TwiML reply."""
    try:
        if not settings.TWILIO_AUTH_TOKEN or not settings.WEBHOOK_PUBLIC_URL:
            logger.error("Twilio webhook configuration is incomplete")
            return _twiml(APOLOGY)

        form = await request.form()
        signature = request.headers.get("X-Twilio-Signature", "")
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        if not validator.validate(settings.WEBHOOK_PUBLIC_URL, dict(form), signature):
            return _twiml(status_code=403)

        from_value = str(form.get("From", ""))
        body = str(form.get("Body", "")).strip()
        message_sid = str(form.get("MessageSid", "")).strip()
        if not message_sid:
            return _twiml(APOLOGY)

        try:
            phone = normalize_phone_number(from_value)
        except ValueError:
            return _twiml(APOLOGY)

        existing = await db.get(WhatsAppMessage, message_sid)
        if existing:
            # A retry gets an empty TwiML response so it cannot trigger a second outbound message.
            return _twiml()
        db.add(WhatsAppMessage(message_sid=message_sid))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return _twiml()

        parsed = parse_message(body)

        if parsed["intent"] == "link_code":
            result, display_name = await consume_link_code(
                db,
                code_value=parsed["code"] or "",
                phone_e164=phone,
            )
            if result == "linked":
                return _twiml(f"Your WhatsApp is now linked to {display_name}.")
            if result == "expired":
                return _twiml("That link code has expired. Generate a new code in Veil Settings → WhatsApp.")
            if result == "used":
                return _twiml("That link code has already been used. Generate a new code in Veil Settings → WhatsApp.")
            return _twiml("That link code is not valid. Check the code and try again.")

        linked = (await db.execute(
            select(WhatsAppLink).where(WhatsAppLink.phone_e164 == phone)
        )).scalars().first()
        if not linked:
            return _twiml(
                "Hi, I'm Veil. Link your account in Settings → WhatsApp to get started. "
                f"{settings.FRONTEND_URL.rstrip('/')}/settings"
            )

        user = await db.get(User, linked.merchant_id)
        if not user:
            return _twiml(APOLOGY)

        session = await db.get(WhatsAppSession, phone)
        now = datetime.now(timezone.utc)
        if session and now - session.updated_at > timedelta(minutes=5):
            await db.delete(session)
            await db.commit()
            session = None

        if parsed["intent"] == "menu":
            return _twiml(MENU)
        if parsed["intent"] == "recent_payments":
            return _twiml(await _recent_payments(db, user.id))
        if parsed["intent"] == "fallback" and (not session or session.state != "awaiting_amount"):
            return _twiml(f"I'm here to help with payments. {MENU}")

        if session and session.state == "awaiting_amount":
            if parsed["intent"] != "create_link":
                parsed = parse_message(f"link {body}")
            if parsed["memo"] and session.draft_memo:
                parsed["memo"] = f"{session.draft_memo} {parsed['memo']}"
            elif session.draft_memo:
                parsed["memo"] = session.draft_memo

        if parsed["intent"] != "create_link" or parsed["amount_ngn"] is None:
            if session and session.state == "awaiting_amount":
                session.updated_at = now
                db.add(session)
                await db.commit()
                return _twiml("Please send an amount in naira, for example 5,000 or 5k.")
            session = WhatsAppSession(
                phone_e164=phone,
                state="awaiting_amount",
                draft_memo=parsed["memo"],
                updated_at=now,
            )
            db.add(session)
            await db.commit()
            return _twiml("How much in naira?")

        if parsed["amount_error"] == "too_low":
            return _twiml("The minimum request is ₦100. Please send an amount of ₦100 or more.")
        if parsed["amount_error"] == "too_high":
            return _twiml("The maximum request is ₦10,000,000. Please send a lower amount.")

        intent = await create_payment_intent(
            db=db,
            user_id=user.id,
            recipient_address=user.address,
            amount_ngn=parsed["amount_ngn"],
            merchant_ref=(parsed["memo"] or "WhatsApp payment")[:120],
            token="USDC",
            memo=parsed["memo"],
            source="whatsapp",
        )
        if session:
            await db.delete(session)
            await db.commit()

        token, token_amount = _token_details(intent)
        checkout_url = f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}"
        reply = (
            f"Checkout link: {checkout_url}\n"
            f"{_format_ngn(parsed['amount_ngn'])} (≈ {token_amount.normalize():f} {token})\n"
            "Valid for 30 minutes."
        )
        return _twiml(reply)
    except Exception:
        logger.exception("WhatsApp webhook processing failed")
        try:
            await db.rollback()
        except Exception:
            logger.exception("Could not rollback failed WhatsApp webhook transaction")
        return _twiml(APOLOGY)
