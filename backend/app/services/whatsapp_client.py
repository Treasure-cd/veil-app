from decimal import Decimal

import httpx
from loguru import logger

from core.config import settings

GRAPH_API_VERSION = "v26.0"


async def send_whatsapp(to_number: str, body: str) -> None:
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
        logger.info("Sent WhatsApp message to {}", to_number)


def format_ngn(value: Decimal | str | None) -> str:
    amount = Decimal(str(value or 0))
    rounded = (
        amount.quantize(Decimal("1"))
        if amount == amount.to_integral()
        else amount.normalize()
    )
    return f"₦{rounded:,.2f}" if rounded != rounded.to_integral() else f"₦{rounded:,.0f}"
