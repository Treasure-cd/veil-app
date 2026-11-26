import hashlib
import hmac
import json
import os
import time
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-chars-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")
os.environ.setdefault("PAJCASH_APIKEY", "paj_test_key")
os.environ.setdefault("PAJCASH_WEBHOOK_SECRET", "whsec_paj_test_secret")

import aiohttp
from aiohttp import web
import jwt
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.models.payment import MerchantBankAccount, PajOfframpOrder, PajOrderStatus, PaymentIntent
from app.models.user import User
from app.services.pajcash import PAJ_SOLANA_TOKENS, PajCashService, verify_paj_webhook
from core.config import settings
from core.session import get_session
from main import app


def _sign_paj_webhook(raw_body: bytes, secret: str = "whsec_paj_test_secret", ts: int | None = None) -> dict[str, str]:
    timestamp = str(ts if ts is not None else int(time.time()))
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-PAJ-Timestamp": timestamp, "X-PAJ-Signature": f"v1={digest}"}


class PajCashServiceTests(unittest.IsolatedAsyncioTestCase):
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

        async with self.session_factory() as db:
            user = User(address=str(Pubkey.new_unique()))
            db.add(user)
            await db.commit()
            await db.refresh(user)
            self.user = user

        self.requests: list[dict] = []
        self.mock_app = web.Application()
        self.mock_app.router.add_route("*", "/{tail:.*}", self._handle_mock)
        self.runner = web.AppRunner(self.mock_app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.mock_responses: dict[tuple[str, str], tuple[int, object]] = {}

    async def asyncTearDown(self) -> None:
        await self.runner.cleanup()
        await self.engine.dispose()

    async def _handle_mock(self, request: web.Request) -> web.Response:
        raw = await request.text()
        self.requests.append({
            "method": request.method,
            "path": request.path,
            "headers": dict(request.headers),
            "body": json.loads(raw) if raw else None,
        })
        status, payload = self.mock_responses.get(
            (request.method, request.path),
            (404, {"message": f"No mock for {request.method} {request.path}"}),
        )
        return web.json_response(payload, status=status)

    async def test_register_bank_account_create_and_reconcile_offramp(self) -> None:
        paj_solana_addr = str(Pubkey.new_unique())
        order_deposit_addr = str(Pubkey.new_unique())
        self.mock_responses[("POST", "/pub/v2/bank-account")] = (
            201,
            {
                "id": "68ff3a4ee9834db8927f61ed",
                "accountName": "JOHN DOE",
                "accountNumber": "0025635480",
                "bank": "First Bank",
                "address": paj_solana_addr,
                "evmAddress": "0x4B0897b0513fdC7C541B6d9D7E929C4e5364D2dB",
            },
        )
        self.mock_responses[("POST", "/pub/v2/offramp")] = (
            201,
            {
                "id": "679be2527f99f556d77b8cc2",
                "address": order_deposit_addr,
                "signature": "",
                "mint": PAJ_SOLANA_TOKENS["SOL"]["mint"],
                "currency": "NGN",
                "amount": 0.05,
                "usdcAmount": 7.5,
                "fiatAmount": 10825,
                "sender": "",
                "recipient": order_deposit_addr,
                "rate": 1443.42,
                "status": "INIT",
                "transactionType": "OFF_RAMP",
                "createdAt": "2026-11-26T12:00:00.000Z",
                "accountNumber": "0025635480",
                "accountName": "JOHN DOE",
                "bank": "First Bank",
                "fee": 0,
                "chain": "SOLANA",
            },
        )
        self.mock_responses[("GET", "/pub/v2/transaction/679be2527f99f556d77b8cc2")] = (
            200,
            {
                "id": "679be2527f99f556d77b8cc2",
                "address": order_deposit_addr,
                "signature": "5VfYk2vQwH3pTq1eXJ9mWZ8cLkNa7RbDsGtUoPiYhE4xCnM6zV1uS2rAjQ3wK8",
                "mint": PAJ_SOLANA_TOKENS["SOL"]["mint"],
                "currency": "NGN",
                "amount": 0.05,
                "usdcAmount": 7.5,
                "fiatAmount": 10825,
                "rate": 1443.42,
                "status": "COMPLETED",
                "transactionType": "OFF_RAMP",
                "fee": 0,
                "chain": "SOLANA",
            },
        )

        async with aiohttp.ClientSession() as http_session:
            service = PajCashService(
                api_key="paj_test_key",
                base_url=self.base_url,
                session=http_session,
            )
            async with self.session_factory() as db:
                account = await service.register_bank_account(
                    db,
                    user_id=self.user.id,
                    bank_code="000016",
                    account_number="0025635480",
                )
                self.assertEqual(account.account_name, "JOHN DOE")
                self.assertEqual(account.solana_address, paj_solana_addr)
                self.assertEqual(self.requests[-1]["headers"]["x-api-key"], "paj_test_key")

                order = await service.create_offramp_order(
                    db,
                    user_id=self.user.id,
                    bank_code="000016",
                    account_number="0025635480",
                    bank_account_id=account.id,
                    mint=PAJ_SOLANA_TOKENS["SOL"]["mint"],
                    token_symbol="SOL",
                    token_decimals=9,
                    fiat_amount="10825",
                    narration="Test SOL offramp",
                )
                self.assertEqual(order.paj_order_id, "679be2527f99f556d77b8cc2")
                self.assertEqual(order.deposit_address, order_deposit_addr)
                self.assertEqual(order.token_amount, "0.05")
                self.assertEqual(order.status, PajOrderStatus.INIT.value)

                reconciled = await service.reconcile_offramp_order(db, order)
                self.assertEqual(reconciled.status, PajOrderStatus.COMPLETED.value)
                self.assertTrue(reconciled.tx_signature)

    def test_paj_webhook_signature_verification(self) -> None:
        raw = b'{"id":"679be2527f99f556d77b8cc2","status":"COMPLETED"}'
        headers = _sign_paj_webhook(raw, secret="whsec_paj_test_secret")
        self.assertTrue(verify_paj_webhook(raw, headers, secret="whsec_paj_test_secret"))

        stale_headers = _sign_paj_webhook(
            raw, secret="whsec_paj_test_secret", ts=int(time.time()) - 400
        )
        self.assertFalse(verify_paj_webhook(raw, stale_headers, secret="whsec_paj_test_secret"))
        self.assertFalse(verify_paj_webhook(raw, {"X-PAJ-Timestamp": headers["X-PAJ-Timestamp"], "X-PAJ-Signature": "v1=bad"}, secret="whsec_paj_test_secret"))


class PajCashRouterTests(unittest.IsolatedAsyncioTestCase):
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
            await db.commit()
            await db.refresh(user)
            self.user = user

        self.token = jwt.encode(
            {"sub": str(self.user.id)}, settings.JWT_SECRET, algorithm="HS256"
        )
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_fiat_settled_intent_and_multi_token_offramp_and_webhook(self) -> None:
        paj_perm_addr = str(Pubkey.new_unique())
        usdt_deposit_addr = str(Pubkey.new_unique())

        async def fake_register(service, db_session, **kwargs):
            row = MerchantBankAccount(
                user_id=kwargs["user_id"],
                paj_account_id="68ff3a4ee9834db8927f61ed",
                bank_code=kwargs["bank_code"],
                bank_name="STERLING BANK",
                account_number=kwargs["account_number"],
                account_name="TEST MERCHANT",
                solana_address=paj_perm_addr,
                is_default=True,
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

        with patch("app.routers.payments.PajCashService.register_bank_account", new=fake_register):
            bank_res = self.client.post(
                "/v1/payments/paj/bank-accounts",
                json={"bankCode": "000001", "accountNumber": "0025635480"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(bank_res.status_code, 200)
            bank_id = bank_res.json()["id"]
            self.assertEqual(bank_res.json()["solanaAddress"], paj_perm_addr)

        with patch(
            "app.services.payment_intents.get_rates",
            new=AsyncMock(return_value={"usdc": Decimal("1500"), "sol": Decimal("220000")}),
        ):
            # 1. Existing crypto flow remains untouched when settlementTarget="crypto"
            crypto_res = self.client.post(
                "/v1/payments/intents",
                json={
                    "merchantRef": "INV-CRYPTO-1",
                    "token": "USDC",
                    "amount_ngn": "3000",
                    "recipientAddress": self.user.address,
                    "receiveMode": "public",
                    "settlementTarget": "crypto",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(crypto_res.status_code, 200)
            self.assertEqual(crypto_res.json()["settlementTarget"], "crypto")
            self.assertEqual(crypto_res.json()["recipientAddress"], self.user.address)

            # 2. Fiat-settled flow routes recipientAddress to Paj bank-account address
            fiat_intent_res = self.client.post(
                "/v1/payments/intents",
                json={
                    "merchantRef": "INV-FIAT-PAJ-1",
                    "token": "USDC",
                    "amount_ngn": "3000",
                    "recipientAddress": self.user.address,
                    "receiveMode": "public",
                    "settlementTarget": "fiat",
                    "bankAccountId": bank_id,
                    "memo": "Shoes order",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(fiat_intent_res.status_code, 200)
            fiat_intent = fiat_intent_res.json()
            self.assertEqual(fiat_intent["settlementTarget"], "fiat")
            self.assertEqual(fiat_intent["recipientAddress"], paj_perm_addr)
            intent_id = fiat_intent["id"]

        # Payer opens checkout and chooses USDT (different token than USDC!)
        async def fake_offramp(service, db_session, **kwargs):
            order = PajOfframpOrder(
                user_id=kwargs["user_id"],
                payment_intent_id=kwargs["payment_intent_id"],
                bank_account_id=kwargs["bank_account_id"],
                paj_order_id="paj_order_usdt_1",
                mint=kwargs["mint"],
                token_symbol=kwargs["token_symbol"],
                token_decimals=kwargs["token_decimals"],
                deposit_address=usdt_deposit_addr,
                token_amount="2.08",
                fiat_amount="3000",
                rate="1443.42",
                bank_code=kwargs["bank_code"],
                bank_name=kwargs["bank_name"],
                account_number=kwargs["account_number"],
                account_name=kwargs["account_name"],
                status=PajOrderStatus.INIT.value,
            )
            db_session.add(order)
            await db_session.commit()
            await db_session.refresh(order)
            return order

        with patch("app.routers.payments.PajCashService.create_offramp_order", new=fake_offramp):
            offramp_res = self.client.post(
                f"/v1/payments/intents/{intent_id}/paj-offramp",
                json={"token": "USDT"},
            )
            self.assertEqual(offramp_res.status_code, 200)
            offramp_data = offramp_res.json()
            self.assertEqual(offramp_data["tokenSymbol"], "USDT")
            self.assertEqual(offramp_data["depositAddress"], usdt_deposit_addr)
            self.assertNotIn("accountNumber", offramp_data)

        # Signed Paj webhook marks order COMPLETED and intent funded
        body_bytes = json.dumps({
            "id": "paj_order_usdt_1",
            "status": "COMPLETED",
            "fiatAmount": 3000,
            "signature": "5VfYk2vQwH3pTq1eXJ9mWZ8cLkNa7RbDsGtUoPiYhE4xCnM6zV1uS2rAjQ3wK8",
        }).encode("utf-8")
        sig_headers = _sign_paj_webhook(body_bytes, secret="whsec_paj_test_secret")
        with patch.object(settings, "PAJCASH_WEBHOOK_SECRET", "whsec_paj_test_secret"):
            wh_res = self.client.post(
                "/v1/webhook/pajcash",
                content=body_bytes,
                headers={"Content-Type": "application/json", **sig_headers},
            )
        self.assertEqual(wh_res.status_code, 200)
        self.assertTrue(wh_res.json()["matched"])

        refreshed = self.client.get(f"/v1/payments/intents/{intent_id}")
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()["status"], "funded")
        self.assertEqual(refreshed.json()["pajOfframp"]["status"], "COMPLETED")

        # Cannot delete a bank account linked to an existing intent
        del_res = self.client.delete(
            f"/v1/payments/paj/bank-accounts/{bank_id}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(del_res.status_code, 409)


if __name__ == "__main__":
    unittest.main()
