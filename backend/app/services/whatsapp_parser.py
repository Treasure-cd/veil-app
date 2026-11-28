"""Pure parser for the Veil WhatsApp command flow."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal, TypedDict


MIN_AMOUNT_NGN = Decimal("100")
MAX_AMOUNT_NGN = Decimal("10000000")
AMOUNT_PATTERN = re.compile(r"(?<![\w.])₦?\s*(\d[\d,]*(?:\.\d+)?\s*[kK]?)(?!\w)")
LINK_CODE_PATTERN = re.compile(r"^\s*link\s+([A-Za-z0-9_-]+)\s*$", re.IGNORECASE)
LOGIN_CODE_PATTERN = re.compile(r"^\s*(?:login|signin|sign\s+in|verify)\s+([A-Za-z0-9_-]+)\s*$", re.IGNORECASE)
FILLER_WORDS = {
    "abeg", "make", "i", "me", "collect", "get", "create", "a", "the", "link",
    "request", "for", "naira", "ngn", "please", "pls", "can", "you", "to", "of",
}


class ParsedMessage(TypedDict):
    intent: Literal[
        "link_code",
        "login_code",
        "menu",
        "recent_payments",
        "daily_summary",
        "rate",
        "create_link",
        "fallback",
    ]
    code: str | None
    amount_ngn: Decimal | None
    memo: str | None
    amount_error: Literal["too_low", "too_high"] | None
    receive_mode: Literal["private", "public"] | None
    crypto_only: bool
    rate_amount: Decimal | None
    rate_currency: Literal["USDC", "SOL"]
    rate_amount_is_token: bool


def _normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    # Keep decimal points, but remove other punctuation so phrases are stable.
    return re.sub(r"[^\w.\s₦]", " ", text)


def _payment_options(text: str) -> tuple[Literal["private", "public"] | None, bool]:
    normalized = _normalized_text(text)
    if re.search(r"\bprivate(?:\s+pay(?:ments?)?)?(?:\s+instead)?\b", normalized):
        receive_mode: Literal["private", "public"] | None = "private"
    elif re.search(r"\bpublic(?:\s+pay(?:ments?)?)?(?:\s+instead)?\b", normalized):
        receive_mode = "public"
    else:
        receive_mode = None

    crypto_only = bool(
        re.search(
            r"\bcrypto\s+to\s+crypto(?:\s+rather\s+than\s+(?:crypto\s+)?bank(?:\s+transfer)?)?\b",
            normalized,
        )
        or re.search(r"\b(?:crypto\s+only|only\s+crypto|just\s+crypto)\b", normalized)
        or re.search(r"\b(?:no|without)\s+(?:the\s+)?bank(?:\s+transfer)?\b", normalized)
    )
    return receive_mode, crypto_only


def _remove_payment_options(text: str) -> str:
    patterns = (
        r"\bprivate(?:\s+pay(?:ments?)?)?(?:\s+instead)?\b",
        r"\bpublic(?:\s+pay(?:ments?)?)?(?:\s+instead)?\b",
        r"\bcrypto\s+to\s+crypto(?:\s+rather\s+than\s+(?:crypto\s+)?bank(?:\s+transfer)?)?\b",
        r"\b(?:crypto\s+only|only\s+crypto|just\s+crypto)\b",
        r"\b(?:no|without)\s+(?:the\s+)?bank(?:\s+transfer)?\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    return text


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
    remainder = _remove_payment_options(_normalized_text(remainder))
    words = [word for word in remainder.split() if word not in FILLER_WORDS and word != "₦"]
    memo = " ".join(words).strip() or None
    error = "too_low" if amount < MIN_AMOUNT_NGN else "too_high" if amount > MAX_AMOUNT_NGN else None
    return amount, memo, error


def _rate_amount(raw_amount: str) -> Decimal:
    raw_amount = re.sub(r"\s+", "", raw_amount).replace(",", "")
    multiplier = Decimal(1000) if raw_amount.endswith("k") else Decimal(1)
    if multiplier == 1000:
        raw_amount = raw_amount[:-1]
    return Decimal(raw_amount) * multiplier


def _parse_rate_query(
    text: str,
) -> tuple[Decimal | None, Literal["USDC", "SOL"], bool] | None:
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = re.sub(r"[^\w.\s]", " ", normalized)
    compact = " ".join(normalized.split())
    amount = r"(\d[\d,]*(?:\.\d+)?\s*[kK]?)"

    token_to_ngn = re.fullmatch(
        rf"(?:rate\s+)?{amount}\s*(usdc|sol)\s+(?:in|to)\s+ngn",
        compact,
    )
    if token_to_ngn:
        currency: Literal["USDC", "SOL"] = (
            "USDC" if token_to_ngn.group(2) == "usdc" else "SOL"
        )
        return (
            _rate_amount(token_to_ngn.group(1)),
            currency,
            True,
        )

    ngn_to_token = re.fullmatch(
        rf"(?:rate|rates|exchange rate|conversion)\s+(?:of\s+)?{amount}"
        rf"(?:\s+(?:in|to)\s+(usdc|sol))?",
        compact,
    ) or re.fullmatch(rf"{amount}\s+(?:in|to)\s+(usdc|sol)", compact)
    if ngn_to_token:
        token = ngn_to_token.group(2) or "usdc"
        currency = "USDC" if token == "usdc" else "SOL"
        return (
            _rate_amount(ngn_to_token.group(1)),
            currency,
            False,
        )

    if compact in {
        "rate",
        "rates",
        "exchange rate",
        "exchange rates",
        "conversion",
        "usdc rate",
        "sol rate",
    }:
        currency: Literal["USDC", "SOL"] = "SOL" if compact == "sol rate" else "USDC"
        return None, currency, False
    return None


def parse_message(text: str) -> ParsedMessage:
    receive_mode, crypto_only = _payment_options(text)
    code_match = LINK_CODE_PATTERN.fullmatch(text)
    code_is_amount = bool(code_match and AMOUNT_PATTERN.fullmatch(code_match.group(1)))
    if code_match and not code_is_amount:
        return {
            "intent": "link_code", "code": code_match.group(1), "amount_ngn": None,
            "memo": None, "amount_error": None, "receive_mode": receive_mode,
            "crypto_only": crypto_only, "rate_amount": None, "rate_currency": "USDC",
            "rate_amount_is_token": False,
        }

    login_match = LOGIN_CODE_PATTERN.fullmatch(text)
    login_is_amount = bool(login_match and AMOUNT_PATTERN.fullmatch(login_match.group(1)))
    if login_match and not login_is_amount:
        return {
            "intent": "login_code", "code": login_match.group(1), "amount_ngn": None,
            "memo": None, "amount_error": None, "receive_mode": receive_mode,
            "crypto_only": crypto_only, "rate_amount": None, "rate_currency": "USDC",
            "rate_amount_is_token": False,
        }

    normalized = _normalized_text(text)
    compact = " ".join(normalized.split())
    rate_query = _parse_rate_query(text)
    if rate_query is not None:
        rate_amount, rate_currency, rate_amount_is_token = rate_query
        return {
            "intent": "rate", "code": None, "amount_ngn": None, "memo": None,
            "amount_error": None, "receive_mode": receive_mode, "crypto_only": crypto_only,
            "rate_amount": rate_amount, "rate_currency": rate_currency,
            "rate_amount_is_token": rate_amount_is_token,
        }

    daily_summary_phrases = {
        "today",
        "summary",
        "daily",
        "daily summary",
        "today s sales",
        "todays sales",
    }
    if compact in daily_summary_phrases:
        return {
            "intent": "daily_summary", "code": None, "amount_ngn": None, "memo": None,
            "amount_error": None, "receive_mode": receive_mode, "crypto_only": crypto_only,
            "rate_amount": None, "rate_currency": "USDC", "rate_amount_is_token": False,
        }

    phrases = {
        "hi", "hello", "hey", "menu", "help", "how far", "wetin i fit do",
    }
    if compact in phrases or any(compact.startswith(f"{phrase} ") for phrase in ("hi", "hello", "hey", "help")):
        return {
            "intent": "menu", "code": None, "amount_ngn": None, "memo": None,
            "amount_error": None, "receive_mode": receive_mode, "crypto_only": crypto_only,
            "rate_amount": None, "rate_currency": "USDC", "rate_amount_is_token": False,
        }

    recent_phrases = {
        "recent", "payments", "sales", "history", "wetin i don collect", "wetin enter",
    }
    if compact in recent_phrases or any(phrase in compact for phrase in recent_phrases):
        return {
            "intent": "recent_payments", "code": None, "amount_ngn": None, "memo": None,
            "amount_error": None, "receive_mode": receive_mode, "crypto_only": crypto_only,
            "rate_amount": None, "rate_currency": "USDC", "rate_amount_is_token": False,
        }

    amount, memo, amount_error = _extract_amount_and_memo(text)
    is_link_request = bool(re.search(r"\b(link|request|collect)\b|make\s+(?:i\s+)?link", normalized))
    if amount is not None or is_link_request:
        if amount is None:
            remainder = _remove_payment_options(normalized)
            words = [word for word in remainder.split() if word not in FILLER_WORDS and word != "₦"]
            memo = " ".join(words).strip() or None
        return {
            "intent": "create_link", "code": None, "amount_ngn": amount, "memo": memo,
            "amount_error": amount_error, "receive_mode": receive_mode,
            "crypto_only": crypto_only, "rate_amount": None, "rate_currency": "USDC",
            "rate_amount_is_token": False,
        }
    return {
        "intent": "fallback", "code": None, "amount_ngn": None, "memo": None,
        "amount_error": None, "receive_mode": receive_mode, "crypto_only": crypto_only,
        "rate_amount": None, "rate_currency": "USDC", "rate_amount_is_token": False,
    }
