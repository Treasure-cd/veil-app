from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
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
from sqlmodel import SQLModel, select

import app.models  # noqa: F401
from app.models.payment import MerchantBankAccount, PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppAuthChallenge, WhatsAppLink
from app.services.whatsapp_linking import _graph_phone_cache
from core.config import settings
from core.session import get_session
from main import app

APP_SECRET = "test-meta-app-secret"


class WhatsAppAuthAndFiatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _graph_phone_cache.clear()
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

    def _post_whatsapp_webhook(self, from_digits: str, text: str, message_id: str):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": from_digits,
                                        "id": message_id,
                                        "type": "text",
                                        "text": {"body": text},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        body = json.dumps(payload).encode()
        sig = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/v1/whatsapp/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={sig}",
            },
        )

    async def test_email_auth_endpoints_removed(self) -> None:
        reg = self.client.post("/v1/auth/register", json={"email": "a@b.com", "password": "password123"})
        login = self.client.post("/v1/auth/login-email", json={"email": "a@b.com", "password": "password123"})
        self.assertEqual(reg.status_code, 404)
        self.assertEqual(login.status_code, 404)

    async def test_standalone_whatsapp_signin_creates_reusable_identity_and_single_use_challenge(self) -> None:
        with patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", "+2348000000000"):
            start = self.client.post("/v1/auth/whatsapp/challenge")

        self.assertEqual(start.status_code, 200, start.text)
        start_body = start.json()
        challenge_token = start_body["challengeToken"]
        code = start_body["code"]
        self.assertEqual(len(code), 6)
        self.assertEqual(
            start_body["sendUrl"],
            f"https://wa.me/2348000000000?text=login%20{code}",
        )

        pending = self.client.get(f"/v1/auth/whatsapp/poll/{challenge_token}")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["status"], "pending")

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
        ):
            webhook_res = self._post_whatsapp_webhook("2348011112222", f"login {code}", "wamid-auth-1")
        self.assertEqual(webhook_res.status_code, 200)
        self.assertIn("You're signed in to Veil", send_reply.await_args.kwargs["body"])

        verified = self.client.get(f"/v1/auth/whatsapp/poll/{challenge_token}")
        self.assertEqual(verified.status_code, 200, verified.text)
        auth_payload = verified.json()
        self.assertEqual(auth_payload["status"], "verified")
        self.assertTrue(auth_payload["token"])
        self.assertFalse(auth_payload["user"]["hasWallet"])
        self.assertTrue(auth_payload["user"]["address"].startswith("whatsapp:"))
        self.assertEqual(auth_payload["user"]["phoneMasked"], "+234••••••2222")
        first_user_id = auth_payload["user"]["id"]

        # Polling a consumed challenge must fail (no token replay).
        replay = self.client.get(f"/v1/auth/whatsapp/poll/{challenge_token}")
        self.assertEqual(replay.status_code, 410)

        # /v1/auth/me reflects WhatsApp identity.
        me = self.client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {auth_payload['token']}"},
        )
        self.assertEqual(me.status_code, 200, me.text)
        self.assertFalse(me.json()["hasWallet"])
        self.assertEqual(me.json()["phoneMasked"], "+234••••••2222")

        # Signing in a second time with the same WhatsApp number resolves the SAME User.
        with patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", "+2348000000000"):
            start2 = self.client.post("/v1/auth/whatsapp/challenge").json()
        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()),
        ):
            self._post_whatsapp_webhook("2348011112222", f"login {start2['code']}", "wamid-auth-2")
        verified2 = self.client.get(f"/v1/auth/whatsapp/poll/{start2['challengeToken']}").json()
        self.assertEqual(verified2["user"]["id"], first_user_id)

    async def test_whatsapp_signin_resolves_existing_linked_wallet_user(self) -> None:
        wallet_address = str(Pubkey.new_unique())
        async with self.session_factory() as db:
            wallet_user = User(address=wallet_address)
            db.add(wallet_user)
            await db.flush()
            db.add(WhatsAppLink(merchant_id=wallet_user.id, phone_e164="+2348022223333", source="code"))
            await db.commit()
            wallet_user_id = str(wallet_user.id)

        with patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", "+2348000000000"):
            challenge = self.client.post("/v1/auth/whatsapp/challenge").json()
        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()),
        ):
            self._post_whatsapp_webhook("2348022223333", f"login {challenge['code']}", "wamid-auth-wallet")

        res = self.client.get(f"/v1/auth/whatsapp/poll/{challenge['challengeToken']}").json()
        self.assertEqual(res["user"]["id"], wallet_user_id)
        self.assertEqual(res["user"]["address"], wallet_address)
        self.assertTrue(res["user"]["hasWallet"])

    async def test_expired_and_used_whatsapp_login_codes_are_rejected(self) -> None:
        async with self.session_factory() as db:
            db.add(
                WhatsAppAuthChallenge(
                    token="expired-tok",
                    code="EXP123",
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            await db.commit()

        poll_expired = self.client.get("/v1/auth/whatsapp/poll/expired-tok")
        self.assertEqual(poll_expired.status_code, 410)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
        ):
            self._post_whatsapp_webhook("2348033334444", "login EXP123", "wamid-auth-exp")
        self.assertIn("expired", send_reply.await_args.kwargs["body"].lower())

    async def test_whatsapp_only_merchant_bot_link_requires_bank_and_routes_to_fiat(self) -> None:
        async with self.session_factory() as db:
            wa_user = User(address=f"whatsapp:{uuid4().hex}")
            db.add(wa_user)
            await db.flush()
            db.add(WhatsAppLink(merchant_id=wa_user.id, phone_e164="+2348044445555", source="auth"))
            await db.commit()
            await db.refresh(wa_user)
            wa_user_id = wa_user.id

        # Before linking a bank account, bot prompts them to add one.
        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
        ):
            res_no_bank = self._post_whatsapp_webhook("2348044445555", "5000 for rice", "wamid-wa-no-bank")
        self.assertEqual(res_no_bank.status_code, 200)
        self.assertIn("bank account", send_reply.await_args.kwargs["body"].lower())

        # Once a bank account is linked, bot creates a fiat-settled intent routed to Paj address.
        bank_solana_address = str(Pubkey.new_unique())
        async with self.session_factory() as db:
            acct = MerchantBankAccount(
                user_id=wa_user_id,
                paj_account_id="paj_wa_1",
                bank_code="058",
                bank_name="GTBank",
                account_number="0123456789",
                account_name="WA Merchant",
                solana_address=bank_solana_address,
            )
            db.add(acct)
            await db.commit()
            await db.refresh(acct)
            acct_id = acct.id

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply2,
            patch(
                "app.services.payment_intents.get_rates",
                new=AsyncMock(return_value={"usdc": Decimal("1600"), "sol": Decimal("240000")}),
            ),
        ):
            res_with_bank = self._post_whatsapp_webhook("2348044445555", "5000 for rice", "wamid-wa-with-bank")

        self.assertEqual(res_with_bank.status_code, 200)
        self.assertIn("settles to NGN", send_reply2.await_args.kwargs["body"])
        async with self.session_factory() as db:
            intent = (await db.execute(select(PaymentIntent).where(PaymentIntent.user_id == wa_user_id))).scalars().first()
        self.assertIsNotNone(intent)
        self.assertEqual(intent.settlement_target, "fiat")
        self.assertEqual(intent.bank_account_id, acct_id)
        self.assertEqual(intent.recipient_address, bank_solana_address)

    async def test_fiat_intent_accepts_whatsapp_placeholder_and_crypto_rejects_it(self) -> None:
        placeholder = f"whatsapp:{uuid4().hex}"
        async with self.session_factory() as db:
            user = User(address=placeholder)
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
                    "merchantRef": "INV-WA-FIAT-1",
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

        crypto_res = self.client.post(
            "/v1/payments/intents",
            json={
                "merchantRef": "INV-WA-CRYPTO-1",
                "token": "USDC",
                "amount_ngn": "5000",
                "recipientAddress": placeholder,
                "receiveMode": "public",
                "settlementTarget": "crypto",
                "includeFiatCheckout": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(crypto_res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
