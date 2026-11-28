from decimal import Decimal
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from types import SimpleNamespace
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
from solders.signature import Signature
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.models.payment import FiatPayment, FiatPaymentFlow, FiatPaymentStatus, PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppLink
from core.config import settings
from core.session import get_session
from app.routers import payments as payment_routes
from app.services.whatsapp_notifications import notify_merchant_payment_received
from main import app


def _sign_webhook(data: dict, secret: str = "whsec_test_secret") -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class FiatRouterTests(unittest.IsolatedAsyncioTestCase):
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
            other = User(address=str(Pubkey.new_unique()))
            db.add(user)
            db.add(other)
            await db.commit()
            await db.refresh(user)
            await db.refresh(other)
            self.user = user
            self.other = other

        self.token = jwt.encode(
            {"sub": str(self.user.id)}, settings.JWT_SECRET, algorithm="HS256"
        )
        self.other_token = jwt.encode(
            {"sub": str(self.other.id)}, settings.JWT_SECRET, algorithm="HS256"
        )
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_payment_alert_is_sent_to_linked_merchant(self) -> None:
        intent = PaymentIntent(
            user_id=self.user.id,
            merchant_ref="INV-ALERT-1",
            mint=settings.USDC_MINT,
            amount_atomic="3120000",
            amount_ngn="5000",
            recipient_address=self.user.address,
            memo="Lunch order",
            status="funded",
        )
        async with self.session_factory() as db:
            db.add(intent)
            db.add(WhatsAppLink(merchant_id=self.user.id, phone_e164="+2348012345678"))
            await db.commit()
            await db.refresh(intent)
            with patch(
                "app.services.whatsapp_notifications.send_whatsapp",
                new=AsyncMock(),
            ) as send_alert:
                await notify_merchant_payment_received(db, intent)

        send_alert.assert_awaited_once()
        phone_number, message = send_alert.await_args.args
        self.assertEqual(phone_number, "+2348012345678")
        self.assertIn("Payment received", message)
        self.assertIn("₦5,000 (≈ 3.12 USDC)", message)
        self.assertIn("Lunch order", message)

    async def test_payment_alert_is_skipped_without_whatsapp_link(self) -> None:
        intent = PaymentIntent(
            user_id=self.user.id,
            merchant_ref="INV-ALERT-2",
            mint=settings.USDC_MINT,
            amount_atomic="1000000",
            amount_ngn="1500",
            recipient_address=self.user.address,
            status="funded",
        )
        async with self.session_factory() as db:
            db.add(intent)
            await db.commit()
            await db.refresh(intent)
            with patch(
                "app.services.whatsapp_notifications.send_whatsapp",
                new=AsyncMock(),
            ) as send_alert:
                await notify_merchant_payment_received(db, intent)

        send_alert.assert_not_awaited()

    async def test_intent_fiat_checkout_and_webhook_marks_intent_funded(self) -> None:
        async with self.session_factory() as db:
            intent = PaymentIntent(
                user_id=self.user.id,
                merchant_ref="INV-ROUTE-1",
                mint=settings.USDC_MINT,
                amount_atomic="1000000",
                amount_ngn="1500",
                recipient_address=self.user.address,
                receive_mode="public",
                memo="Logo design",
            )
            db.add(intent)
            await db.commit()
            await db.refresh(intent)

        checkout_id = str(uuid4())

        async def fake_create_checkout(service, db_session, **kwargs):
            row = FiatPayment(
                user_id=kwargs["user_id"],
                payment_intent_id=kwargs["payment_intent_id"],
                flow=FiatPaymentFlow.CHECKOUT.value,
                reference=kwargs["reference"],
                idempotency_key=str(uuid4()),
                fossapay_id=checkout_id,
                amount="1500.00",
                fee="100.00",
                amount_payable="1600.00",
                settlement_amount="1500.00",
                fee_bearer=kwargs["fee_bearer"],
                account_type="order_wallet",
                bank_name="Sterling Bank",
                account_name="Veil Checkout",
                account_number="9712110507",
                status=FiatPaymentStatus.PENDING.value,
                description=kwargs.get("description"),
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

        with patch("app.routers.payments.FossaPayService.create_checkout", new=fake_create_checkout):
            res = self.client.post(f"/v1/payments/intents/{intent.id}/fiat-checkout")
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(body["accountNumber"], "9712110507")
            self.assertEqual(body["amountPayable"], "1600.00")
            self.assertNotIn("fossapayId", body)

            # Second call reuses existing pending checkout idempotently
            res2 = self.client.post(f"/v1/payments/intents/{intent.id}/fiat-checkout")
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.json()["id"], body["id"])

        # GET intent exposes fiatCheckout to payer
        intent_res = self.client.get(f"/v1/payments/intents/{intent.id}")
        self.assertEqual(intent_res.status_code, 200)
        self.assertEqual(intent_res.json()["fiatCheckout"]["accountNumber"], "9712110507")

        # Unsigned webhook is rejected
        bad_webhook = self.client.post(
            "/v1/webhook/fossapay",
            json={"eventId": "evt_1", "eventType": "checkout.completed", "data": {"status": "completed"}},
            headers={"x-fossapay-Signature": "invalid"},
        )
        self.assertEqual(bad_webhook.status_code, 401)

        # Valid signed webhook completes FiatPayment and funds linked PaymentIntent
        data = {
            "checkoutId": checkout_id,
            "transactionId": str(uuid4()),
            "reference": body["reference"],
            "status": "completed",
            "amount": "1500.00",
            "fee": "100.00",
            "amountPayable": "1600.00",
            "settlementAmount": "1500.00",
            "completedAt": "2026-11-25T21:40:00.000Z",
        }
        webhook_payload = {
            "eventId": "evt_route_completed_1",
            "eventType": "checkout.completed",
            "data": data,
            "timestamp": "2026-11-25T21:40:01.000Z",
        }
        with patch.object(settings, "FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret"):
            async with self.session_factory() as db:
                db.add(WhatsAppLink(merchant_id=self.user.id, phone_e164="+2348012345678"))
                await db.commit()
            with patch(
                "app.services.whatsapp_notifications.send_whatsapp",
                new=AsyncMock(side_effect=RuntimeError("Meta API unavailable")),
            ) as send_alert:
                ok_webhook = self.client.post(
                    "/v1/webhook/fossapay",
                    json=webhook_payload,
                    headers={"x-fossapay-Signature": _sign_webhook(data)},
                )
                duplicate_webhook = self.client.post(
                    "/v1/webhook/fossapay",
                    json=webhook_payload,
                    headers={"x-fossapay-Signature": _sign_webhook(data)},
                )
                self.assertEqual(duplicate_webhook.status_code, 200)
                send_alert.assert_awaited_once()
                message = send_alert.await_args.args[1]
                self.assertIn("Payment received", message)
                self.assertIn("₦1,500", message)
                self.assertIn("Logo design", message)
                self.assertIn(f"{settings.FRONTEND_URL.rstrip('/')}/payments", message)
        self.assertEqual(ok_webhook.status_code, 200)
        self.assertTrue(ok_webhook.json()["accepted"])

        funded_intent = self.client.get(f"/v1/payments/intents/{intent.id}")
        self.assertEqual(funded_intent.status_code, 200)
        self.assertEqual(funded_intent.json()["status"], "funded")
        self.assertEqual(funded_intent.json()["fiatCheckout"]["status"], "completed")

    async def test_private_funding_uses_umbra_verifier_and_hides_fund_signature(self) -> None:
        async with self.session_factory() as db:
            intent = PaymentIntent(
                user_id=self.user.id,
                merchant_ref="INV-PRIVATE-1",
                mint=settings.USDC_MINT,
                amount_atomic="1000000",
                amount_ngn="1500",
                recipient_address=self.user.address,
                receive_mode="private",
                memo="Private checkout",
            )
            db.add(intent)
            await db.commit()
            await db.refresh(intent)

        with (
            patch(
                "app.routers.payments.verify_umbra_deposit",
                new=AsyncMock(return_value=True),
            ) as verify_umbra,
            patch(
                "app.routers.payments.verify_transfer",
                new=AsyncMock(side_effect=AssertionError("public verification must not run")),
            ),
        ):
            funded = self.client.post(
                f"/v1/payments/intents/{intent.id}/confirm-fund",
                json={"signature": "1" * 64},
            )
            self.assertEqual(funded.status_code, 200)
            self.assertEqual(funded.json()["status"], "funded")
            verify_umbra.assert_awaited_once()

        public_intent = self.client.get(f"/v1/payments/intents/{intent.id}")
        self.assertEqual(public_intent.status_code, 200)
        self.assertNotIn("fundSignature", public_intent.json())
        self.assertNotIn("payerAddress", public_intent.json())

    async def test_umbra_verifier_requires_successful_program_call_and_exact_token_debit(self) -> None:
        now = datetime.now(timezone.utc)
        amount = "1000000"

        def make_transaction(program_id: str, payer_debit: str):
            return SimpleNamespace(
                block_time=int(now.timestamp()),
                transaction=SimpleNamespace(
                    meta=SimpleNamespace(
                        err=None,
                        pre_token_balances=[
                            SimpleNamespace(
                                mint=settings.USDC_MINT,
                                owner="payer",
                                ui_token_amount=SimpleNamespace(amount=amount),
                            )
                        ],
                        post_token_balances=[
                            SimpleNamespace(
                                mint=settings.USDC_MINT,
                                owner="payer",
                                ui_token_amount=SimpleNamespace(amount=payer_debit),
                            ),
                            SimpleNamespace(
                                mint=settings.USDC_MINT,
                                owner="umbra-pool",
                                ui_token_amount=SimpleNamespace(amount=amount),
                            ),
                        ],
                        inner_instructions=[],
                    ),
                    transaction=SimpleNamespace(
                        message=SimpleNamespace(
                            instructions=[SimpleNamespace(program_id=program_id)]
                        )
                    ),
                ),
            )

        async def verify(transaction, expected_amount: str) -> bool:
            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def get_transaction(self, *_args, **_kwargs):
                    return SimpleNamespace(value=transaction)

            with patch.object(settings, "SOLANA_NETWORK", "mainnet-beta"), patch(
                "app.routers.payments.AsyncClient",
                return_value=FakeClient(),
            ):
                return await payment_routes.verify_umbra_deposit(
                    str(Signature.default()),
                    settings.USDC_MINT,
                    expected_amount,
                    now - timedelta(seconds=5),
                )

        program_id = payment_routes.UMBRA_PROGRAM_IDS["mainnet-beta"]
        self.assertTrue(await verify(make_transaction(program_id, "0"), amount))
        self.assertFalse(await verify(make_transaction(program_id, "0"), "1000001"))
        self.assertFalse(await verify(make_transaction("not-umbra", "0"), amount))

    async def test_merchant_fiat_payout_and_ownership_isolation(self) -> None:
        with (
            patch(
                "app.routers.payments.FossaPayService.get_supported_banks",
                new=AsyncMock(return_value=[{"bankname": "Guaranty Trust Bank", "bankcode": "058"}]),
            ),
            patch(
                "app.routers.payments.FossaPayService.verify_bank_account",
                new=AsyncMock(return_value={"accountNumber": "0123456789", "accountName": "JOHN DOE"}),
            ),
            patch(
                "app.routers.payments.FossaPayService.calculate_transfer_fee",
                new=AsyncMock(return_value={"amount": 5000, "currency": "NGN", "feeAmount": 20, "total": 5020}),
            ),
        ):
            banks = self.client.get(
                "/v1/payments/fiat/banks",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(banks.status_code, 200)
            self.assertEqual(banks.json()[0]["bankcode"], "058")

            enquiry = self.client.post(
                "/v1/payments/fiat/bank-name-enquiry",
                json={"bankCode": "058", "accountNumber": "0123456789"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(enquiry.status_code, 200)
            self.assertEqual(enquiry.json()["accountName"], "JOHN DOE")

            fee = self.client.get(
                "/v1/payments/fiat/fee?amount=5000",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(fee.status_code, 200)
            self.assertEqual(fee.json()["feeAmount"], 20)

        async def fake_create_payout(service, db_session, **kwargs):
            row = FiatPayment(
                user_id=kwargs["user_id"],
                flow=FiatPaymentFlow.PAYOUT.value,
                reference=kwargs["reference"],
                idempotency_key=kwargs.get("idempotency_key") or str(uuid4()),
                fossapay_id=str(uuid4()),
                amount="5000.00",
                fee="20.00",
                total_debited="5020.00",
                route="external_bank",
                bank_code=kwargs["bank_code"],
                bank_name=kwargs["bank_name"],
                account_name=kwargs["account_name"],
                account_number=kwargs["account_number"],
                status=FiatPaymentStatus.PROCESSING.value,
                description=kwargs.get("remarks"),
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

        with patch("app.routers.payments.FossaPayService.create_payout", new=fake_create_payout):
            created = self.client.post(
                "/v1/payments/fiat/payouts",
                json={
                    "amountNgn": 5000,
                    "bankCode": "058",
                    "bankName": "Guaranty Trust Bank",
                    "accountNumber": "0123456789",
                    "accountName": "JOHN DOE",
                    "remarks": "Vendor cash-out",
                    "idempotencyKey": "ui-payout-1",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(created.status_code, 200)
            payout_id = created.json()["id"]
            self.assertEqual(created.json()["totalDebited"], "5020.00")

        # Another merchant cannot view or reconcile this payout
        forbidden = self.client.get(
            f"/v1/payments/fiat/{payout_id}",
            headers={"Authorization": f"Bearer {self.other_token}"},
        )
        self.assertEqual(forbidden.status_code, 404)

        listed = self.client.get(
            "/v1/payments/fiat?flow=payout",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

    async def test_create_intent_with_fiat_checkout_option(self) -> None:
        async def fake_create_checkout(service, db_session, **kwargs):
            row = FiatPayment(
                user_id=kwargs["user_id"],
                payment_intent_id=kwargs["payment_intent_id"],
                flow=FiatPaymentFlow.CHECKOUT.value,
                reference=kwargs["reference"],
                idempotency_key=str(uuid4()),
                fossapay_id=str(uuid4()),
                amount="2000.00",
                fee="100.00",
                amount_payable="2000.00",
                settlement_amount="1900.00",
                fee_bearer=kwargs["fee_bearer"],
                account_type="order_wallet",
                bank_name="Sterling Bank",
                account_name="Veil Checkout",
                account_number="9712110999",
                status=FiatPaymentStatus.PENDING.value,
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

        with (
            patch(
                "app.services.payment_intents.get_rates",
                new=AsyncMock(return_value={"usdc": Decimal("1600"), "sol": Decimal("240000")}),
            ),
            patch("app.routers.payments.FossaPayService.create_checkout", new=fake_create_checkout),
        ):
            res = self.client.post(
                "/v1/payments/intents",
                json={
                    "merchantRef": "INV-FIAT-OPT-1",
                    "token": "USDC",
                    "amount_ngn": "2000",
                    "recipientAddress": self.user.address,
                    "receiveMode": "public",
                    "memo": "Design retainer",
                    "includeFiatCheckout": True,
                    "feeBearer": "merchant",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(res.status_code, 200)
            payload = res.json()
            self.assertIsNotNone(payload["fiatCheckout"])
            self.assertEqual(payload["fiatCheckout"]["feeBearer"], "merchant")
            self.assertEqual(payload["fiatCheckout"]["settlementAmount"], "1900.00")
            self.assertEqual(payload["fiatCheckout"]["accountNumber"], "9712110999")

    async def test_expire_fiat_checkout_reconciles_completed_intent_on_conflict(self) -> None:
        async with self.session_factory() as db:
            intent = PaymentIntent(
                user_id=self.user.id,
                merchant_ref="INV-EXPIRE-COMP-1",
                mint=settings.USDC_MINT,
                amount_atomic="1000000",
                amount_ngn="2000",
                recipient_address=self.user.address,
                receive_mode="public",
                memo="Expire vs complete race",
            )
            db.add(intent)
            await db.commit()
            await db.refresh(intent)

            fiat_row = FiatPayment(
                user_id=self.user.id,
                payment_intent_id=intent.id,
                flow=FiatPaymentFlow.CHECKOUT.value,
                reference="CHK-EXPIRE-RACE-1",
                idempotency_key=str(uuid4()),
                fossapay_id=str(uuid4()),
                amount="2000.00",
                status=FiatPaymentStatus.PENDING.value,
            )
            db.add(fiat_row)
            await db.commit()
            await db.refresh(fiat_row)

        async def fake_expire_completed(service, db_session, payment):
            payment.status = FiatPaymentStatus.COMPLETED.value
            db_session.add(payment)
            await db_session.commit()
            await db_session.refresh(payment)
            from app.services.payment import FossaPayError

            raise FossaPayError(
                "Only a pending checkout can be expired; current status is completed",
                status_code=409,
            )

        with patch("app.routers.payments.FossaPayService.expire_checkout", new=fake_expire_completed):
            res = self.client.post(
                f"/v1/payments/fiat/{fiat_row.id}/expire",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(res.status_code, 409)

        async with self.session_factory() as db:
            refreshed_intent = await db.get(PaymentIntent, intent.id)
            self.assertEqual(refreshed_intent.status, "funded")


if __name__ == "__main__":
    unittest.main()
