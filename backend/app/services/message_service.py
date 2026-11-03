import httpx
from core.config import settings
from loguru import logger

headers = {
    "Authorization": f"Bearer {settings.WASENDER_API_KEY}",
    "Content-Type": "application/json",
}

url = "https://www.wasenderapi.com/api/send-message"


async def send_msg(phone_number: str, message: str):
    """Send a message to a specified phone number using the Wasender API."""
    data = {
        "to": f"+{phone_number}",
        "text": f"{message}",
    }

    if settings.WASENDER_API_KEY == "mock-wasender-api-key":
        logger.info(f"MOCK Sending message to {data['to']} with content: {message}")
        return {"status": "success", "mock": True}

    async with httpx.AsyncClient() as client:
        logger.info(f"Sending message to {data['to']} with content: {message}")
        response = await client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()