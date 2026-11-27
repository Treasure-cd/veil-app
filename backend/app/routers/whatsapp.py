import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from twilio.request_validator import RequestValidator
from twilio.rest import Client
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

MENU = (
    "I can help with payments. Try: `link 5000 for lunch`, `link 5000 private`, "
    "`link 5000 crypto only`, `recent`, or `help`."
)
APOLOGY = "Sorry, Veil couldn't process that just now. Please try again shortly."


def _twiml(status_code: int = 200) -> Response:
    xml = str(MessagingResponse())
    logger.info("TwiML reply ({}): {}", status_code, xml)
    return Response(content=xml, status_code=status_code, media_type="application/xml")


def _send_whatsapp(to_number: str, from_number: str, body: str) -> None:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio REST API credentials are not configured")

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    to_wa = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    from_wa = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"
    if settings.TWILIO_CONTENT_SID:
        message = client.messages.create(
            from_=from_wa,
            to=to_wa,
            content_sid=settings.TWILIO_CONTENT_SID,
            content_variables=json.dumps({"1": body}),
        )
    else:
        message = client.messages.create(from_=from_wa, to=to_wa, body=body)
    logger.info("Sent WhatsApp reply {} to {}", message.sid, to_wa)


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
    token = "USDC" if intent.mint in settings.known_usdc_mints else "SOL"
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
    """Receive Twilio messages, reply through the REST API, and return empty TwiML."""
    from_value = ""
    to_value = ""
    reply_attempted = False
    sender_valid = False

    try:
        logger.info("Received Twilio WhatsApp webhook")
        if (
            not settings.TWILIO_AUTH_TOKEN
            or not settings.WEBHOOK_PUBLIC_URL
            or not settings.TWILIO_ACCOUNT_SID
        ):
            logger.error("Twilio webhook configuration is incomplete")
            return _twiml()

        form = await request.form()
        signature = request.headers.get("X-Twilio-Signature", "")
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        if not validator.validate(settings.WEBHOOK_PUBLIC_URL, dict(form), signature):
            logger.warning("Twilio WhatsApp signature validation failed")
            return _twiml(status_code=403)

        from_value = str(form.get("From", ""))
        to_value = str(form.get("To", ""))
        logger.info("Inbound WhatsApp addresses: From={} To={}", from_value, to_value)

        if not to_value:
            logger.warning("Twilio WhatsApp webhook did not include a To number")
            return _twiml()

        async def reply(text: str) -> Response:
            nonlocal reply_attempted
            reply_attempted = True
            await asyncio.to_thread(
                _send_whatsapp,
                to_number=from_value,
                from_number=to_value,
                body=text,
            )
            return _twiml()

        body = str(form.get("Body", "")).strip()
        message_sid = str(form.get("MessageSid", "")).strip()
        if not message_sid:
            logger.warning("Twilio WhatsApp webhook did not include a message SID")
            return _twiml()

        try:
            phone = normalize_phone_number(from_value)
        except ValueError:
            logger.warning("Twilio WhatsApp webhook included an invalid sender number")
            return _twiml()
        sender_valid = True

        existing = await db.get(WhatsAppMessage, message_sid)
        if existing:
            # A retry gets an empty TwiML response so it cannot trigger a second outbound message.
            logger.info("Ignoring duplicate Twilio WhatsApp message {}", message_sid)
            return _twiml()
        db.add(WhatsAppMessage(message_sid=message_sid))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info("Ignoring duplicate Twilio WhatsApp message {}", message_sid)
            return _twiml()

        logger.info("Processing Twilio WhatsApp message {}", message_sid)
        parsed = parse_message(body)

        if parsed["intent"] == "link_code":
            result, display_name = await consume_link_code(
                db,
                code_value=parsed["code"] or "",
                phone_e164=phone,
            )
            if result == "linked":
                return await reply(f"Your WhatsApp is now linked to {display_name}.")
            if result == "expired":
                return await reply("That link code has expired. Generate a new code in Veil Settings → WhatsApp.")
            if result == "used":
                return await reply("That link code has already been used. Generate a new code in Veil Settings → WhatsApp.")
            return await reply("That link code is not valid. Check the code and try again.")

        linked = (await db.execute(
            select(WhatsAppLink).where(WhatsAppLink.phone_e164 == phone)
        )).scalars().first()
        if not linked:
            return await reply(
                "Hi, I'm Veil. Link your account in Settings → WhatsApp to get started. "
                f"{settings.FRONTEND_URL.rstrip('/')}/settings"
            )

        user = await db.get(User, linked.merchant_id)
        if not user:
            return await reply(APOLOGY)

        session = await db.get(WhatsAppSession, phone)
        now = datetime.now(timezone.utc)
        if session and now - session.updated_at > timedelta(minutes=5):
            await db.delete(session)
            await db.commit()
            session = None

        if parsed["intent"] == "menu":
            return await reply(MENU)
        if parsed["intent"] == "recent_payments":
            return await reply(await _recent_payments(db, user.id))
        if parsed["intent"] == "fallback" and (not session or session.state != "awaiting_amount"):
            return await reply(f"I'm here to help with payments. {MENU}")

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
                return await reply("Please send an amount in naira, for example 5,000 or 5k.")
            session = WhatsAppSession(
                phone_e164=phone,
                state="awaiting_amount",
                draft_memo=parsed["memo"],
                updated_at=now,
            )
            db.add(session)
            await db.commit()
            return await reply("How much in naira?")

        if parsed["amount_error"] == "too_low":
            return await reply("The minimum request is ₦100. Please send an amount of ₦100 or more.")
        if parsed["amount_error"] == "too_high":
            return await reply("The maximum request is ₦10,000,000. Please send a lower amount.")

        receive_mode = parsed["receive_mode"] or (
            "private" if settings.WHATSAPP_PRIVATE_PAYMENTS else "public"
        )
        allow_fiat_checkout = (
            "fossapay" in settings.whatsapp_payment_methods
            and not parsed["crypto_only"]
            and receive_mode != "private"
        )
        intent = await create_payment_intent(
            db=db,
            user_id=user.id,
            recipient_address=user.address,
            amount_ngn=parsed["amount_ngn"],
            merchant_ref=(parsed["memo"] or "WhatsApp payment")[:120],
            token="USDC",
            memo=parsed["memo"],
            source="whatsapp",
            receive_mode=receive_mode,
            allow_fiat_checkout=allow_fiat_checkout,
        )
        if session:
            await db.delete(session)
            await db.commit()

        token, token_amount = _token_details(intent)
        checkout_url = f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}"
        if receive_mode == "private":
            payment_options = "private USDC only"
        elif allow_fiat_checkout:
            payment_options = "USDC or bank transfer"
        else:
            payment_options = "USDC only"
        reply_text = (
            f"Checkout link: {checkout_url}\n"
            f"{_format_ngn(parsed['amount_ngn'])} (≈ {token_amount.normalize():f} {token})\n"
            f"Payment options: {payment_options}.\n"
            "Valid for 30 minutes."
        )
        return await reply(reply_text)
    except Exception:
        logger.exception("WhatsApp webhook processing failed")
        try:
            await db.rollback()
        except Exception:
            logger.exception("Could not rollback failed WhatsApp webhook transaction")
        if sender_valid and not reply_attempted:
            try:
                await asyncio.to_thread(
                    _send_whatsapp,
                    to_number=from_value,
                    from_number=to_value,
                    body=APOLOGY,
                )
            except Exception:
                logger.exception("Could not send WhatsApp failure reply")
        return _twiml()
