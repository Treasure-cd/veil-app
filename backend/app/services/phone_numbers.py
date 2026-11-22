import re


def normalize_phone_number(value: str, default_country_code: str = "+234") -> str:
    """Normalize WhatsApp or plain phone input to an E.164 number."""
    value = value.strip()
    if value.lower().startswith("whatsapp:"):
        value = value[len("whatsapp:"):].strip()
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise ValueError("Phone number is empty")
    if value.startswith("+"):
        normalized = f"+{digits}"
    elif digits.startswith("0"):
        normalized = f"{default_country_code}{digits[1:]}"
    else:
        normalized = f"+{digits}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
        raise ValueError("Phone number is not a valid E.164 number")
    return normalized
