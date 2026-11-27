import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")

from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import app.models  # noqa: F401
from app.models.user import User
from app.models.whatsapp import WhatsAppLink
from core.config import settings
from core.session import get_session
from main import app


class WhatsAppDemoLinkTests(unittest.IsolatedAsyncioTestCase):
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
            self.demo_wallet = User(address=str(Pubkey.new_unique()))
            db.add(self.demo_wallet)
            await db.commit()
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_guest_can_get_demo_link_to_shared_wallet(self) -> None:
        with (
            patch.object(settings, "WHATSAPP_DEMO_MODE", "true"),
            patch.object(
                settings, "WHATSAPP_DEMO_MERCHANT_WALLET", self.demo_wallet.address
            ),
            patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", "+14155238886"),
        ):
            response = self.client.post(
                "/v1/whatsapp/demo-link",
                json={"phone": "08012345678"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "https://wa.me/14155238886",
            response.json()["join_url"],
        )
        async with self.session_factory() as db:
            link = (
                await db.execute(
                    select(WhatsAppLink).where(
                        WhatsAppLink.phone_e164 == "+2348012345678"
                    )
                )
            ).scalars().first()
        self.assertIsNotNone(link)
        self.assertEqual(link.merchant_id, self.demo_wallet.id)
        self.assertEqual(link.source, "demo")


if __name__ == "__main__":
    unittest.main()
