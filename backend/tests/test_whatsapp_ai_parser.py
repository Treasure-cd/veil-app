import asyncio
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")

from app.services.whatsapp_ai_parser import (
    GeminiWhatsAppParse,
    _clients_by_key,
    parse_message_with_gemini,
)
from core.config import Settings, settings


class WhatsAppAIParserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _clients_by_key.clear()

    def test_settings_accepts_gemini_apikey_alias(self) -> None:
        cfg = Settings(
            _env_file=None,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            JWT_SECRET="test-jwt-secret-at-least-32-characters-long",
            FOSSAPAY_API_KEY="fk_test_key",
            FOSSAPAY_SECRET="test_secret",
            FOSSAPAY_WEBHOOK_SECRET="whsec_test_secret",
            GEMINI_APIKEY="alias-key-123",
        )
        self.assertEqual(cfg.GEMINI_API_KEY, "alias-key-123")
        self.assertEqual(cfg.GEMINI_MODEL, "gemini-3.5-flash-lite")

    async def test_returns_fallback_without_calling_gemini_when_unconfigured(self) -> None:
        with (
            patch.object(settings, "GEMINI_API_KEY", None),
            patch("app.services.whatsapp_ai_parser.genai.Client") as client_cls,
        ):
            result = await parse_message_with_gemini("abeg send link for 15k")

        self.assertEqual(result["intent"], "fallback")
        self.assertIsNone(result["amount_ngn"])
        client_cls.assert_not_called()

    async def test_parses_structured_output_and_enforces_amount_bounds(self) -> None:
        mock_generate = AsyncMock(
            side_effect=[
                SimpleNamespace(
                    parsed=GeminiWhatsAppParse(
                        intent="create_link",
                        amount_ngn=15000.0,
                        memo="Chidi   sneakers\norder",
                        receive_mode="private",
                        crypto_only=True,
                    ),
                    text=None,
                ),
                SimpleNamespace(
                    parsed=None,
                    text='{"intent":"create_link","amount_ngn":50,"memo":"gum","receive_mode":null,"crypto_only":false}',
                ),
                SimpleNamespace(
                    parsed=GeminiWhatsAppParse(
                        intent="create_link",
                        amount_ngn=20000000.0,
                        memo="house",
                        receive_mode=None,
                        crypto_only=False,
                    ),
                    text=None,
                ),
            ]
        )
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_generate

        with (
            patch.object(settings, "GEMINI_API_KEY", "test-gemini-key"),
            patch.object(settings, "GEMINI_MODEL", "gemini-3.5-flash"),
            patch("app.services.whatsapp_ai_parser.genai.Client", return_value=mock_client),
        ):
            ok = await parse_message_with_gemini("bill Chidi fifteen thousand for sneakers private crypto only")
            low = await parse_message_with_gemini("collect fifty naira for gum")
            high = await parse_message_with_gemini("twenty million naira for house")

        self.assertEqual(ok["intent"], "create_link")
        self.assertEqual(ok["amount_ngn"], Decimal("15000.0"))
        self.assertEqual(ok["memo"], "Chidi sneakers order")
        self.assertEqual(ok["receive_mode"], "private")
        self.assertTrue(ok["crypto_only"])
        self.assertIsNone(ok["amount_error"])

        self.assertEqual(low["intent"], "create_link")
        self.assertEqual(low["amount_error"], "too_low")

        self.assertEqual(high["intent"], "create_link")
        self.assertEqual(high["amount_error"], "too_high")
        self.assertEqual(mock_generate.await_count, 3)

    async def test_returns_fallback_on_gemini_error_or_timeout(self) -> None:
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=asyncio.TimeoutError())

        with (
            patch.object(settings, "GEMINI_API_KEY", "test-gemini-timeout-key"),
            patch("app.services.whatsapp_ai_parser.genai.Client", return_value=mock_client),
        ):
            result = await parse_message_with_gemini("abeg send me link")

        self.assertEqual(result["intent"], "fallback")
        self.assertIsNone(result["amount_ngn"])

    async def test_omits_thinking_config_for_flash_lite_3_5(self) -> None:
        mock_generate = AsyncMock(
            return_value=SimpleNamespace(
                parsed=GeminiWhatsAppParse(
                    intent="recent_payments",
                    amount_ngn=None,
                    memo=None,
                    receive_mode=None,
                    crypto_only=False,
                ),
                text=None,
            )
        )
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_generate

        with (
            patch.object(settings, "GEMINI_API_KEY", "test-gemini-lite-key"),
            patch.object(settings, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
            patch("app.services.whatsapp_ai_parser.genai.Client", return_value=mock_client),
        ):
            result = await parse_message_with_gemini("who has paid me today")

        self.assertEqual(result["intent"], "recent_payments")
        cfg = mock_generate.await_args.kwargs["config"]
        self.assertIsNone(cfg.thinking_config)


if __name__ == "__main__":
    unittest.main()
