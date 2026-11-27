import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.payment import PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppMessage, WhatsAppSession
from app.services.payment_intents import create_payment_intent
from app.services.phone_numbers import normalize_phone_number
from app.services.whatsapp_ai_parser import parse_message_with_gemini
from app.services.whatsapp_linking import consume_link_code
from app.services.whatsapp_parser import parse_message
from core.config import settings
from core.session import get_session

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

GRAPH_API_VERSION = "v26.0"

MENU = (
    "I can help with payments. Try: `link 5000 for lunch`, `link 5000 private`, "
    "`link 5000 crypto only`, `recent`, or `help`."
)
APOLOGY = "Sorry, Veil couldn't process that just now. Please try again shortly."


def _valid_meta_signature(raw_body: bytes, signature: str, app_secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.get("/webhook")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    verify_token = settings.WHATSAPP_VERIFY_TOKEN
    if (
        hub_mode != "subscribe"
        or not verify_token
        or not hmac.compare_digest(hub_verify_token, verify_token)
    ):
        return Response(status_code=403)
    return PlainTextResponse(content=hub_challenge)


async def _send_whatsapp(to_number: str, body: str) -> None:
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("Meta WhatsApp Cloud API credentials are not configured")

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number.lstrip("+"),
        "type": "text",
        "text": {"body": body},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        logger.info("Sent WhatsApp reply to {}", to_number)


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


async def _build_inbound_reply(
    db: AsyncSession,
    from_raw: str,
    body: str,
) -> str | None:
    try:
        try:
            phone = normalize_phone_number(f"+{from_raw.lstrip('+')}")
        except ValueError:
            logger.warning("Meta WhatsApp webhook included an invalid sender number: {}", from_raw)
            return None

        parsed = parse_message(body)

        if parsed["intent"] == "link_code":
            result, display_name = await consume_link_code(
                db,
                code_value=parsed["code"] or "",
                phone_e164=phone,
            )
            if result == "linked":
                return f"Your WhatsApp is now linked to {display_name}."
            if result == "expired":
                return "That link code has expired. Generate a new code in Veil Settings → WhatsApp."
            if result == "used":
                return "That link code has already been used. Generate a new code in Veil Settings → WhatsApp."
            return "That link code is not valid. Check the code and try again."

        linked = (await db.execute(
            select(WhatsAppLink).where(WhatsAppLink.phone_e164 == phone)
        )).scalars().first()
        if not linked:
            return (
                "Hi, I'm Veil. Link your account in Settings → WhatsApp to get started. "
                f"{settings.FRONTEND_URL.rstrip('/')}/settings"
            )

        user = await db.get(User, linked.merchant_id)
        if not user:
            return APOLOGY

        session = await db.get(WhatsAppSession, phone)
        now = datetime.now(timezone.utc)
        if session:
            session_updated = (
                session.updated_at.replace(tzinfo=timezone.utc)
                if session.updated_at.tzinfo is None
                else session.updated_at
            )
            if now - session_updated > timedelta(minutes=5):
                await db.delete(session)
                await db.commit()
                session = None

        awaiting_amount = bool(session and session.state == "awaiting_amount")
        if parsed["intent"] == "fallback":
            if awaiting_amount:
                prefixed = parse_message(f"link {body}")
                if prefixed["amount_ngn"] is not None or prefixed["amount_error"] is not None:
                    parsed = prefixed
            if parsed["intent"] == "fallback":
                parsed = await parse_message_with_gemini(
                    body,
                    awaiting_amount=awaiting_amount,
                )

        if parsed["intent"] == "menu":
            return MENU
        if parsed["intent"] == "recent_payments":
            return await _recent_payments(db, user.id)
        if parsed["intent"] == "fallback" and not awaiting_amount:
            return f"I'm here to help with payments. {MENU}"

        if awaiting_amount and session is not None:
            if parsed["memo"] and session.draft_memo:
                parsed["memo"] = f"{session.draft_memo} {parsed['memo']}"
            elif session.draft_memo:
                parsed["memo"] = session.draft_memo

        if parsed["intent"] != "create_link" or parsed["amount_ngn"] is None:
            if session and session.state == "awaiting_amount":
                session.updated_at = now
                db.add(session)
                await db.commit()
                return "Please send an amount in naira, for example 5,000 or 5k."
            session = WhatsAppSession(
                phone_e164=phone,
                state="awaiting_amount",
                draft_memo=parsed["memo"],
                updated_at=now,
            )
            db.add(session)
            await db.commit()
            return "How much in naira?"

        if parsed["amount_error"] == "too_low":
            return "The minimum request is ₦100. Please send an amount of ₦100 or more."
        if parsed["amount_error"] == "too_high":
            return "The maximum request is ₦10,000,000. Please send a lower amount."

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
        return (
            f"Checkout link: {checkout_url}\n"
            f"{_format_ngn(parsed['amount_ngn'])} (≈ {token_amount.normalize():f} {token})\n"
            f"Payment options: {payment_options}.\n"
            "Valid for 30 minutes."
        )
    except Exception:
        logger.exception("WhatsApp message handling failed")
        try:
            await db.rollback()
        except Exception:
            logger.exception("Could not rollback failed WhatsApp transaction")
        return APOLOGY


async def _handle_inbound_message(
    db: AsyncSession,
    from_raw: str,
    body: str,
    message_id: str,
) -> str | None:
    message = await db.get(WhatsAppMessage, message_id)
    if message:
        if message.reply_text is not None:
            if message.replied_at is not None:
                logger.info("Ignoring duplicate Meta WhatsApp message {}", message_id)
                return None
            return message.reply_text or None

        received_at = message.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - received_at < timedelta(minutes=2):
            raise HTTPException(
                status_code=503,
                detail="WhatsApp message is still being processed",
            )
        message.received_at = datetime.now(timezone.utc)
        await db.commit()
    else:
        message = WhatsAppMessage(message_sid=message_id)
        db.add(message)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            message = await db.get(WhatsAppMessage, message_id)
            if not message or message.reply_text is None:
                raise HTTPException(
                    status_code=503,
                    detail="WhatsApp message is still being processed",
                )
            if message.replied_at is not None:
                return None
            return message.reply_text or None

    logger.info("Processing Meta WhatsApp message {}", message_id)
    reply_text = await _build_inbound_reply(db, from_raw, body)
    message = await db.get(WhatsAppMessage, message_id)
    if not message:
        raise RuntimeError("WhatsApp message record disappeared during processing")
    message.reply_text = reply_text or ""
    if not reply_text:
        message.replied_at = datetime.now(timezone.utc)
    await db.commit()
    return reply_text


@router.post("/webhook")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_session)):
    """Receive Meta WhatsApp Cloud API webhooks and reply via Graph API."""
    app_secret = settings.WHATSAPP_APP_SECRET
    if not app_secret:
        logger.error("Meta WhatsApp webhook app secret is not configured")
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured")

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _valid_meta_signature(raw_body, signature, app_secret):
        logger.warning("Meta WhatsApp webhook signature validation failed")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid webhook payload")
        logger.info("Received Meta WhatsApp webhook")

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue

                    from_raw = str(msg.get("from", "")).strip()
                    body = str(msg.get("text", {}).get("body", "")).strip()
                    message_id = str(msg.get("id", "")).strip()
                    if not from_raw or not message_id:
                        continue

                    reply_text = await _handle_inbound_message(
                        db=db,
                        from_raw=from_raw,
                        body=body,
                        message_id=message_id,
                    )
                    if reply_text:
                        await _send_whatsapp(to_number=from_raw, body=reply_text)
                        message = await db.get(WhatsAppMessage, message_id)
                        if not message:
                            raise RuntimeError("WhatsApp message record disappeared after sending")
                        message.replied_at = datetime.now(timezone.utc)
                        await db.commit()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("Meta WhatsApp webhook processing failed")
        raise HTTPException(
            status_code=503,
            detail="WhatsApp webhook processing failed",
        )

    return {"status": "ok"}