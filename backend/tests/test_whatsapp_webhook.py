import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")

from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from twilio.request_validator import RequestValidator

import app.models  # noqa: F401
from app.models.payment import PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppLink
from core.config import settings
from core.session import get_session
from main import app


class WhatsAppWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_get_session():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        async with self.session_factory() as db:
            user = User(address=str(Pubkey.new_unique()))
            db.add(user)
            await db.flush()
            db.add(WhatsAppLink(merchant_id=user.id, phone_e164="+2348012345678"))
            await db.commit()
            self.user = user
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_twilio_form_message_returns_configured_checkout_link(self) -> None:
        auth_token = "test-twilio-token"
        webhook_url = "https://api.example.test/v1/whatsapp/webhook"
        intent = PaymentIntent(
            id=uuid4(),
            user_id=self.user.id,
            merchant_ref="WhatsApp payment",
            mint=settings.USDC_MINT,
            amount_atomic="1000000",
            amount_ngn="5000",
            rate_ngn_per_token="1500",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            recipient_address=self.user.address,
            receive_mode="public",
            allow_fiat_checkout=True,
            memo="lunch",
        )
        form = {
            "From": "whatsapp:+2348012345678",
            "Body": "5000 for lunch",
            "MessageSid": "SM-test-whatsapp-checkout",
        }
        signature = RequestValidator(auth_token).compute_signature(webhook_url, form)

        with (
            patch.object(settings, "TWILIO_AUTH_TOKEN", auth_token),
            patch.object(settings, "WEBHOOK_PUBLIC_URL", webhook_url),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            response = self.client.post(
                "/v1/whatsapp/webhook",
                data=form,
                headers={"X-Twilio-Signature": signature},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/xml")
        self.assertIn(f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}", response.text)
        self.assertIn("Checkout link:", response.text)
        create_intent.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["token"], "USDC")
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "public")
        self.assertTrue(create_intent.await_args.kwargs["allow_fiat_checkout"])

    async def test_vendor_can_request_private_crypto_only_checkout(self) -> None:
        auth_token = "test-twilio-token"
        webhook_url = "https://api.example.test/v1/whatsapp/webhook"
        intent = PaymentIntent(
            id=uuid4(),
            user_id=self.user.id,
            merchant_ref="WhatsApp payment",
            mint=settings.USDC_MINT,
            amount_atomic="1000000",
            amount_ngn="5000",
            rate_ngn_per_token="1500",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            recipient_address=self.user.address,
            receive_mode="private",
            allow_fiat_checkout=False,
            memo="lunch",
        )
        form = {
            "From": "whatsapp:+2348012345678",
            "Body": "5000 for lunch private crypto only",
            "MessageSid": "SM-test-whatsapp-private-crypto-only",
        }
        signature = RequestValidator(auth_token).compute_signature(webhook_url, form)

        with (
            patch.object(settings, "TWILIO_AUTH_TOKEN", auth_token),
            patch.object(settings, "WEBHOOK_PUBLIC_URL", webhook_url),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            response = self.client.post(
                "/v1/whatsapp/webhook",
                data=form,
                headers={"X-Twilio-Signature": signature},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("private USDC only", response.text)
        self.assertIn(f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}", response.text)
        create_intent.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "private")
        self.assertFalse(create_intent.await_args.kwargs["allow_fiat_checkout"])


if __name__ == "__main__":
    unittest.main()
