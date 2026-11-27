"""Gemini structured-output fallback parser for conversational WhatsApp messages."""
import asyncio
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel, Field

from app.services.whatsapp_parser import (
    MAX_AMOUNT_NGN,
    MIN_AMOUNT_NGN,
    ParsedMessage,
)
from core.config import settings

_GEMINI_TIMEOUT_SECONDS = 8.0
_clients_by_key: dict[str, genai.Client] = {}

_SYSTEM_INSTRUCTION = (
    "You are an intent and parameter parser for Veil, a Nigerian payment link bot on WhatsApp. "
    "Understand English and Nigerian Pidgin messages from merchants and return ONLY structured JSON matching the schema. "
    "Never execute queries, generate links, or invent amounts. "
    "Convert Naira shorthand accurately (e.g. '5k' -> 5000, '2.5k' -> 2500, '1.5m' -> 1500000, "
    "'fifteen thousand' -> 15000). "
    "If the user wants to create or send a payment request/link but gave no amount, set intent='create_link' and amount_ngn=null. "
    "Only set receive_mode='private' if they explicitly ask for private/shielded payment, or 'public' if explicitly public. "
    "Only set crypto_only=true if they explicitly ask for crypto-only, USDC-only, or no bank transfer. "
    "Use intent='fallback' for chit-chat, unrelated requests, or unclear messages."
)


class GeminiWhatsAppParse(BaseModel):
    """Typed JSON contract produced by Gemini when regex parsing falls back."""

    intent: Literal["create_link", "recent_payments", "menu", "fallback"] = Field(
        description=(
            "'create_link' when asking to request/collect/bill money or giving an amount for a link; "
            "'recent_payments' when asking about recent sales, transactions, or payments received; "
            "'menu' for greetings or asking for help/options; 'fallback' otherwise."
        )
    )
    amount_ngn: float | None = Field(
        default=None,
        description="Requested payment amount in Nigerian Naira (NGN), or null if not stated.",
    )
    memo: str | None = Field(
        default=None,
        description="Short description/item/customer note (max 120 chars), excluding currency, filler, and mode flags.",
    )
    receive_mode: Literal["private", "public"] | None = Field(
        default=None,
        description="Explicit privacy mode ('private' or 'public'), or null when unspecified.",
    )
    crypto_only: bool = Field(
        default=False,
        description="True only when explicitly requesting crypto-only / no bank transfer.",
    )


def _fallback_message() -> ParsedMessage:
    return {
        "intent": "fallback",
        "code": None,
        "amount_ngn": None,
        "memo": None,
        "amount_error": None,
        "receive_mode": None,
        "crypto_only": False,
    }


def _get_client(api_key: str) -> genai.Client:
    client = _clients_by_key.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key)
        _clients_by_key[api_key] = client
    return client


def _to_parsed_message(parsed: GeminiWhatsAppParse) -> ParsedMessage:
    amount_decimal: Decimal | None = None
    amount_error: Literal["too_low", "too_high"] | None = None

    if parsed.amount_ngn is not None and math.isfinite(parsed.amount_ngn):
        try:
            candidate = Decimal(str(parsed.amount_ngn))
        except InvalidOperation:
            candidate = None
        if candidate is not None:
            amount_decimal = candidate
            if candidate < MIN_AMOUNT_NGN:
                amount_error = "too_low"
            elif candidate > MAX_AMOUNT_NGN:
                amount_error = "too_high"

    memo = re.sub(r"\s+", " ", parsed.memo or "").strip()[:120] or None

    return {
        "intent": parsed.intent,
        "code": None,
        "amount_ngn": amount_decimal,
        "memo": memo,
        "amount_error": amount_error,
        "receive_mode": parsed.receive_mode,
        "crypto_only": bool(parsed.crypto_only),
    }


async def parse_message_with_gemini(
    text: str,
    *,
    awaiting_amount: bool = False,
) -> ParsedMessage:
    """Parse an unmatched WhatsApp message into a typed ParsedMessage using Gemini."""
    api_key = (settings.GEMINI_API_KEY or "").strip()
    cleaned = text.strip()
    if not api_key or not cleaned:
        return _fallback_message()

    model_name = (settings.GEMINI_MODEL or "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
    prompt = (
        f"Context: Veil previously asked the merchant 'How much in naira?' for a draft payment link.\n"
        f"Merchant message: {cleaned}"
        if awaiting_amount
        else f"Merchant message: {cleaned}"
    )
    config_kwargs: dict = {
        "system_instruction": _SYSTEM_INSTRUCTION,
        "temperature": 0,
        "response_mime_type": "application/json",
        "response_schema": GeminiWhatsAppParse,
    }
    supports_thinking_zero = (
        any(tag in model_name for tag in ("2.5-flash", "3.5-flash", "3.6-flash", "3.7-flash", "3.8-flash", "3.1-flash-lite"))
        and "3.5-flash-lite" not in model_name
    )
    if supports_thinking_zero:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    try:
        client = _get_client(api_key)
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            ),
            timeout=_GEMINI_TIMEOUT_SECONDS,
        )
        parsed = response.parsed
        if not isinstance(parsed, GeminiWhatsAppParse):
            if isinstance(parsed, dict):
                parsed = GeminiWhatsAppParse.model_validate(parsed)
            elif getattr(response, "text", None):
                parsed = GeminiWhatsAppParse.model_validate_json(response.text)
            else:
                return _fallback_message()
        return _to_parsed_message(parsed)
    except Exception as exc:
        logger.warning("Gemini WhatsApp fallback parser failed: {}", exc)
        return _fallback_message()
