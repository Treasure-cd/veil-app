from decimal import Decimal
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-chars-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")

import jwt
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.models.payment import MerchantBankAccount
from app.models.user import User
from core.config import settings
from core.session import get_session
from main import app


class EmailAuthAndFiatTests(unittest.IsolatedAsyncioTestCase):
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
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_register_login_and_me_for_email_account(self) -> None:
        registered = self.client.post(
            "/v1/auth/register",
            json={"email": "merchant@example.com", "password": "supersecret"},
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        payload = registered.json()
        self.assertEqual(payload["user"]["email"], "merchant@example.com")
        self.assertTrue(payload["user"]["address"].startswith("email:"))

        me = self.client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {payload['token']}"},
        )
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["email"], "merchant@example.com")

        duplicate = self.client.post(
            "/v1/auth/register",
            json={"email": "merchant@example.com", "password": "supersecret"},
        )
        self.assertEqual(duplicate.status_code, 409)

        wrong_password = self.client.post(
            "/v1/auth/login-email",
            json={"email": "merchant@example.com", "password": "wrong-password"},
        )
        self.assertEqual(wrong_password.status_code, 401)

        logged_in = self.client.post(
            "/v1/auth/login-email",
            json={"email": "merchant@example.com", "password": "supersecret"},
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.text)
        self.assertTrue(logged_in.json()["token"])

    async def test_short_password_is_rejected(self) -> None:
        res = self.client.post(
            "/v1/auth/register",
            json={"email": "short@example.com", "password": "short"},
        )
        self.assertEqual(res.status_code, 400)

    async def test_fiat_intent_accepts_email_placeholder_and_routes_to_bank(self) -> None:
        placeholder = f"email:{uuid4().hex}"
        async with self.session_factory() as db:
            user = User(
                address=placeholder,
                email="fiat@example.com",
                password_hash="unused",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

            bank_solana_address = str(Pubkey.new_unique())
            account = MerchantBankAccount(
                user_id=user.id,
                paj_account_id="paj_acct_1",
                bank_code="058",
                bank_name="Guaranty Trust Bank",
                account_number="0123456789",
                account_name="Fiat Merchant",
                solana_address=bank_solana_address,
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)
            account_id = str(account.id)
            token = jwt.encode(
                {"sub": str(user.id)}, settings.JWT_SECRET, algorithm="HS256"
            )

        with patch(
            "app.services.payment_intents.get_rates",
            new=AsyncMock(
                return_value={"usdc": Decimal("1600"), "sol": Decimal("240000")}
            ),
        ):
            res = self.client.post(
                "/v1/payments/intents",
                json={
                    "merchantRef": "INV-EMAIL-FIAT-1",
                    "token": "USDC",
                    "amount_ngn": "5000",
                    "recipientAddress": placeholder,
                    "receiveMode": "public",
                    "settlementTarget": "fiat",
                    "bankAccountId": account_id,
                    "includeFiatCheckout": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertEqual(payload["settlementTarget"], "fiat")
        self.assertEqual(payload["recipientAddress"], bank_solana_address)
        self.assertEqual(payload["receiveMode"], "public")

    async def test_crypto_intent_still_requires_valid_solana_address(self) -> None:
        async with self.session_factory() as db:
            user = User(address=f"email:{uuid4().hex}", email="crypto@example.com")
            db.add(user)
            await db.commit()
            await db.refresh(user)
            token = jwt.encode(
                {"sub": str(user.id)}, settings.JWT_SECRET, algorithm="HS256"
            )

        res = self.client.post(
            "/v1/payments/intents",
            json={
                "merchantRef": "INV-EMAIL-CRYPTO-1",
                "token": "USDC",
                "amount_ngn": "5000",
                "recipientAddress": "email:not-a-pubkey",
                "receiveMode": "public",
                "settlementTarget": "crypto",
                "includeFiatCheckout": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
