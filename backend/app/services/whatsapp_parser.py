"""Pure parser for the Veil WhatsApp command flow."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal, TypedDict


MIN_AMOUNT_NGN = Decimal("100")
MAX_AMOUNT_NGN = Decimal("10000000")
AMOUNT_PATTERN = re.compile(r"(?<![\w.])₦?\s*(\d[\d,]*(?:\.\d+)?\s*[kK]?)(?!\w)")
LINK_CODE_PATTERN = re.compile(r"^\s*link\s+([A-Za-z0-9_-]+)\s*$", re.IGNORECASE)
FILLER_WORDS = {
    "abeg", "make", "i", "me", "collect", "get", "create", "a", "the", "link",
    "request", "for", "naira", "ngn", "please", "pls", "can", "you", "to", "of",
}


class ParsedMessage(TypedDict):
    intent: Literal["link_code", "menu", "recent_payments", "create_link", "fallback"]
    code: str | None
    amount_ngn: Decimal | None
    memo: str | None
    amount_error: Literal["too_low", "too_high"] | None


def _normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    # Keep decimal points, but remove other punctuation so phrases are stable.
    return re.sub(r"[^\w.\s₦]", " ", text)


def _extract_amount_and_memo(text: str) -> tuple[Decimal | None, str | None, str | None]:
    match = AMOUNT_PATTERN.search(text)
    if not match:
        return None, None, None

    raw_amount = re.sub(r"\s+", "", match.group(1)).replace(",", "")
    multiplier = Decimal(1000) if raw_amount.lower().endswith("k") else Decimal(1)
    if multiplier == 1000:
        raw_amount = raw_amount[:-1]
    try:
        amount = Decimal(raw_amount) * multiplier
    except InvalidOperation:
        return None, None, None

    remainder = f"{text[:match.start()]} {text[match.end():]}"
    remainder = _normalized_text(remainder)
    words = [word for word in remainder.split() if word not in FILLER_WORDS and word != "₦"]
    memo = " ".join(words).strip() or None
    error = "too_low" if amount < MIN_AMOUNT_NGN else "too_high" if amount > MAX_AMOUNT_NGN else None
    return amount, memo, error


def parse_message(text: str) -> ParsedMessage:
    code_match = LINK_CODE_PATTERN.fullmatch(text)
    code_is_amount = bool(code_match and AMOUNT_PATTERN.fullmatch(code_match.group(1)))
    if code_match and not code_is_amount:
        return {"intent": "link_code", "code": code_match.group(1), "amount_ngn": None, "memo": None, "amount_error": None}

    normalized = _normalized_text(text)
    compact = " ".join(normalized.split())
    phrases = {
        "hi", "hello", "hey", "menu", "help", "how far", "wetin i fit do",
    }
    if compact in phrases or any(compact.startswith(f"{phrase} ") for phrase in ("hi", "hello", "hey", "help")):
        return {"intent": "menu", "code": None, "amount_ngn": None, "memo": None, "amount_error": None}

    recent_phrases = {
        "recent", "payments", "sales", "history", "wetin i don collect", "wetin enter",
    }
    if compact in recent_phrases or any(phrase in compact for phrase in recent_phrases):
        return {"intent": "recent_payments", "code": None, "amount_ngn": None, "memo": None, "amount_error": None}

    amount, memo, amount_error = _extract_amount_and_memo(text)
    is_link_request = bool(re.search(r"\b(link|request|collect)\b|make\s+(?:i\s+)?link", normalized))
    if amount is not None or is_link_request:
        if amount is None:
            words = [word for word in normalized.split() if word not in FILLER_WORDS and word != "₦"]
            memo = " ".join(words).strip() or None
        return {"intent": "create_link", "code": None, "amount_ngn": amount, "memo": memo, "amount_error": amount_error}
    return {"intent": "fallback", "code": None, "amount_ngn": None, "memo": None, "amount_error": None}
