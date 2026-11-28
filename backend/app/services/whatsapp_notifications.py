from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.payment import PaymentIntent
from app.models.whatsapp import WhatsAppLink
from app.services.whatsapp_client import format_ngn, send_whatsapp
from core.config import settings


async def notify_merchant_payment_received(
    db: AsyncSession, intent: PaymentIntent
) -> None:
    try:
        link = (
            await db.execute(
                select(WhatsAppLink).where(WhatsAppLink.merchant_id == intent.user_id)
            )
        ).scalars().first()
        if link is None:
            return

        token = "USDC" if intent.mint in settings.known_usdc_mints else "SOL"
        decimals = 6 if token == "USDC" else 9
        token_amount = Decimal(intent.amount_atomic) / (Decimal(10) ** decimals)
        display_token_amount = format(token_amount.normalize(), "f")
        header = "Payment claimed" if intent.status == "claimed" else "Payment received"
        lines = [
            header,
            f"{format_ngn(intent.amount_ngn)} (≈ {display_token_amount} {token})",
        ]
        reference = intent.memo or intent.merchant_ref
        if reference:
            lines.append(f"Reference: {reference}")
        lines.append(f"View payments: {settings.FRONTEND_URL.rstrip('/')}/payments")

        await send_whatsapp(link.phone_e164, "\n".join(lines))
    except Exception:
        logger.exception(
            "Failed to send WhatsApp payment alert for intent {}", intent.id
        )
