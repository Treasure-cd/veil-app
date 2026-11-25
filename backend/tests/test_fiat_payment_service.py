import hashlib
import hmac
import json
import os
import unittest
from uuid import uuid4

# Ensure Settings can initialize during test imports without requiring production secrets.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-chars-long")
os.environ.setdefault("FOSSAPAY_API_KEY", "fk_test_key")
os.environ.setdefault("FOSSAPAY_SECRET", "test_secret")
os.environ.setdefault("FOSSAPAY_WEBHOOK_SECRET", "whsec_test_secret")

import aiohttp
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.models.payment import FiatPaymentFlow, FiatPaymentStatus
from app.models.user import User
from app.services.payment import (
    FossaPayError,
    FossaPayService,
    verify_fossapay_webhook,
)


def _sign_webhook(data: dict, secret: str = "whsec_test_secret") -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class FiatPaymentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        async with self.session_factory() as db:
            user = User(address="5hzTestWalletAddress11111111111111111111111")
            db.add(user)
            await db.commit()
            await db.refresh(user)
            self.user_id = user.id

        self.requests: list[dict] = []
        self.mock_app = web.Application()
        self.mock_app.router.add_route("*", "/{tail:.*}", self._handle_mock_request)
        self.runner = web.AppRunner(self.mock_app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.mock_responses: dict[tuple[str, str], tuple[int, dict]] = {}

    async def asyncTearDown(self) -> None:
        await self.runner.cleanup()
        await self.engine.dispose()

    async def _handle_mock_request(self, request: web.Request) -> web.Response:
        raw = await request.text()
        self.requests.append(
            {
                "method": request.method,
                "path": request.path,
                "headers": dict(request.headers),
                "body": json.loads(raw) if raw else None,
            }
        )
        status, payload = self.mock_responses.get(
            (request.method, request.path),
            (404, {"message": f"No mock for {request.method} {request.path}"}),
        )
        return web.json_response(payload, status=status)

    async def test_create_and_reconcile_checkout_and_webhook_dedup(self) -> None:
        checkout_id = "35f5f6fb-0c8d-4e96-ba4a-c04750724ff6"
        self.mock_responses[("POST", "/api/v1/checkouts")] = (
            201,
            {
                "status": "success",
                "statusCode": 201,
                "message": "Checkout session created successfully",
                "data": {
                    "id": checkout_id,
                    "reference": "ORDER-10025",
                    "status": "pending",
                    "amount": "5000.00",
                    "fee": "80.00",
                    "amountPayable": "5080.00",
                    "settlementAmount": "5000.00",
                    "feeBearer": "customer",
                    "split": {"code": "SPL_0123456789ABCDEF", "version": 1, "status": "attached"},
                    "currency": "NGN",
                    "account": {
                        "type": "order_wallet",
                        "bankName": "Sterling Bank",
                        "accountName": "FOSSAPAY CHECKOUT",
                        "accountNumber": "9541382701",
                        "expiresAt": "2026-09-11T10:30:00+01:00",
                    },
                    "customer": None,
                    "metadata": {"orderId": "10025"},
                    "transactionId": "3469cd26-a213-431e-96c9-72dc2dea51ae",
                    "providerCheckoutReference": None,
                    "expiresAt": "2026-09-11T10:30:00+01:00",
                    "completedAt": None,
                    "failedAt": None,
                    "reversedAt": None,
                    "createdAt": "2026-09-11T10:00:00+01:00",
                    "updatedAt": "2026-09-11T10:00:00+01:00",
                },
            },
        )

        async with aiohttp.ClientSession() as http_session:
            service = FossaPayService(
                api_key="fk_test_key",
                base_url=self.base_url,
                session=http_session,
            )
            async with self.session_factory() as db:
                payment = await service.create_checkout(
                    db,
                    user_id=self.user_id,
                    amount_ngn=5000,
                    reference="ORDER-10025",
                    fee_bearer="customer",
                    split_code="SPL_0123456789ABCDEF",
                    metadata={"orderId": "10025"},
                    idempotency_key="idem-checkout-1",
                )

                self.assertEqual(payment.flow, FiatPaymentFlow.CHECKOUT.value)
                self.assertEqual(payment.fossapay_id, checkout_id)
                self.assertEqual(payment.amount_payable, "5080.00")
                self.assertEqual(payment.account_type, "order_wallet")
                self.assertEqual(payment.split_code, "SPL_0123456789ABCDEF")
                self.assertEqual(json.loads(payment.metadata_json), {"orderId": "10025"})
                self.assertEqual(payment.account_number, "9541382701")
                self.assertEqual(payment.bank_name, "Sterling Bank")
                self.assertEqual(payment.status, FiatPaymentStatus.PENDING.value)
                self.assertEqual(self.requests[-1]["headers"]["x-api-key"], "fk_test_key")
                self.assertEqual(
                    self.requests[-1]["headers"]["X-Idempotency-Key"], "idem-checkout-1"
                )

                # Retry with the same reference short-circuits without duplicating API calls
                replayed = await service.create_checkout(
                    db,
                    user_id=self.user_id,
                    amount_ngn=5000,
                    reference="ORDER-10025",
                )
                self.assertEqual(replayed.id, payment.id)
                self.assertEqual(len(self.requests), 1)

                # Simulate checkout.completed webhook
                webhook_body = {
                    "eventId": "evt_checkout_001",
                    "eventType": "checkout.completed",
                    "data": {
                        "checkoutId": checkout_id,
                        "transactionId": "3469cd26-a213-431e-96c9-72dc2dea51ae",
                        "reference": "ORDER-10025",
                        "status": "completed",
                        "amount": "5000.00",
                        "fee": "80.00",
                        "amountPayable": "5080.00",
                        "settlementAmount": "5000.00",
                        "feeBearer": "customer",
                        "currency": "NGN",
                        "accountType": "order_wallet",
                        "providerReference": "100004260911021740170939156478",
                        "expiresAt": "2026-09-11T10:30:00.000Z",
                        "completedAt": "2026-09-11T10:08:14.148Z",
                        "failedAt": None,
                        "reversedAt": None,
                    },
                    "timestamp": "2026-09-11T10:08:14.186Z",
                }
                sig = _sign_webhook(webhook_body["data"])

                self.assertTrue(
                    verify_fossapay_webhook(
                        webhook_body,
                        {"x-fossapay-Signature": sig},
                        secret="whsec_test_secret",
                    )
                )
                self.assertFalse(
                    verify_fossapay_webhook(
                        webhook_body,
                        {"x-fossapay-Signature": "bad"},
                        secret="whsec_test_secret",
                    )
                )

                accepted, updated = await service.process_webhook(db, webhook_body)
                self.assertTrue(accepted)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.status, FiatPaymentStatus.COMPLETED.value)
                self.assertEqual(updated.last_event_id, "evt_checkout_001")

                # Duplicate eventId must be ignored idempotently without expiring caller state
                accepted_dup, dup_payment = await service.process_webhook(db, webhook_body)
                self.assertFalse(accepted_dup)
                self.assertIsNone(dup_payment)
                self.assertEqual(updated.status, FiatPaymentStatus.COMPLETED.value)

    async def test_checkout_mismatch_and_non_regression(self) -> None:
        checkout_id = str(uuid4())
        self.mock_responses[("POST", "/api/v1/checkouts")] = (
            201,
            {
                "status": "success",
                "statusCode": 201,
                "message": "Created",
                "data": {
                    "id": checkout_id,
                    "reference": "ORDER-MISMATCH-1",
                    "status": "pending",
                    "amount": "5000.00",
                    "fee": "100.00",
                    "amountPayable": "5000.00",
                    "settlementAmount": "4900.00",
                    "feeBearer": "merchant",
                    "currency": "NGN",
                    "account": {
                        "type": "permanent",
                        "bankName": "Sterling Bank",
                        "accountName": "Peni",
                        "accountNumber": "9710000000",
                        "expiresAt": None,
                    },
                    "customer": None,
                    "metadata": None,
                    "transactionId": None,
                    "providerCheckoutReference": None,
                    "expiresAt": "2026-09-11T10:30:00.000Z",
                    "completedAt": None,
                    "failedAt": None,
                    "reversedAt": None,
                    "createdAt": "2026-09-11T10:00:00.000Z",
                    "updatedAt": "2026-09-11T10:00:00.000Z",
                },
            },
        )

        async with aiohttp.ClientSession() as http_session:
            service = FossaPayService(
                api_key="fk_test_key",
                base_url=self.base_url,
                session=http_session,
            )
            async with self.session_factory() as db:
                payment = await service.create_checkout(
                    db,
                    user_id=self.user_id,
                    amount_ngn=5000,
                    reference="ORDER-MISMATCH-1",
                    fee_bearer="merchant",
                )
                self.assertEqual(payment.fee_bearer, "merchant")
                self.assertEqual(payment.amount_payable, "5000.00")
                self.assertEqual(payment.settlement_amount, "4900.00")

                accepted, updated = await service.process_webhook(
                    db,
                    {
                        "eventId": "evt_underpaid_1",
                        "eventType": "checkout.failed",
                        "data": {
                            "checkoutId": checkout_id,
                            "transactionId": str(uuid4()),
                            "reference": "ORDER-MISMATCH-1",
                            "status": "failed",
                            "paymentOutcome": "underpaid",
                            "expectedAmount": "5000.00",
                            "receivedAmount": "4500.00",
                            "failedAt": "2026-09-11T10:12:29.048Z",
                        },
                    },
                )
                self.assertTrue(accepted)
                self.assertEqual(updated.status, FiatPaymentStatus.FAILED.value)
                self.assertEqual(updated.payment_outcome, "underpaid")
                self.assertEqual(updated.received_amount, "4500.00")

                # Out-of-order non-terminal webhook must not regress terminal status
                accepted2, updated2 = await service.process_webhook(
                    db,
                    {
                        "eventId": "evt_late_reverse_1",
                        "eventType": "checkout.reversed",
                        "data": {
                            "checkoutId": checkout_id,
                            "reference": "ORDER-MISMATCH-1",
                            "status": "reversed",
                            "reversedAt": "2026-09-11T10:13:00.000Z",
                        },
                    },
                )
                self.assertTrue(accepted2)
                self.assertEqual(updated2.status, FiatPaymentStatus.REVERSED.value)

    async def test_bank_enquiry_and_payout_lifecycle_and_webhook(self) -> None:
        payout_id = "a9af907d-965f-4ad8-9472-f437fc11df21"
        self.mock_responses[("POST", "/api/v1/transfers/fiat/bank-name-enquiry")] = (
            201,
            {
                "status": True,
                "statusCode": 201,
                "message": "Bank name enquiry completed successfully",
                "data": {
                    "accountNumber": "0123456789",
                    "accountName": "JOHN DOE",
                    "sessionId": None,
                },
            },
        )
        self.mock_responses[("POST", "/api/v1/payouts")] = (
            202,
            {
                "status": "success",
                "statusCode": 202,
                "message": "Payout accepted",
                "data": {
                    "payoutId": payout_id,
                    "transactionId": "5a0bb85c-268b-44fa-a57d-70b2944688bc",
                    "reference": "PAYOUT-10025",
                    "status": "processing",
                    "route": "external_bank",
                    "amount": "5000.00",
                    "fee": "80.00",
                    "totalDebited": "5080.00",
                    "currency": "NGN",
                    "recipient": {
                        "bankCode": "058",
                        "bankName": "Guaranty Trust Bank",
                        "accountName": "JOHN DOE",
                        "accountNumber": "0123456789",
                    },
                    "providerReference": None,
                    "metadata": None,
                    "completedAt": None,
                    "failedAt": None,
                    "reversedAt": None,
                },
            },
        )
        self.mock_responses[("GET", f"/api/v1/payouts/{payout_id}")] = (
            200,
            {
                "status": "success",
                "statusCode": 200,
                "message": "Payout retrieved",
                "data": {
                    "payoutId": payout_id,
                    "transactionId": "5a0bb85c-268b-44fa-a57d-70b2944688bc",
                    "reference": "PAYOUT-10025",
                    "status": "completed",
                    "route": "external_bank",
                    "amount": "5000.00",
                    "fee": "80.00",
                    "totalDebited": "5080.00",
                    "currency": "NGN",
                    "recipient": {
                        "bankCode": "058",
                        "bankName": "Guaranty Trust Bank",
                        "accountName": "JOHN DOE",
                        "accountNumber": "0123456789",
                    },
                    "providerReference": "PYT_123",
                    "metadata": None,
                    "completedAt": "2026-09-11T12:05:10.000Z",
                    "failedAt": None,
                    "reversedAt": None,
                },
            },
        )

        async with aiohttp.ClientSession() as http_session:
            service = FossaPayService(
                api_key="fk_test_key",
                base_url=self.base_url,
                session=http_session,
            )
            enquiry = await service.verify_bank_account(
                bank_code="058", account_number="0123456789"
            )
            self.assertEqual(enquiry["accountName"], "JOHN DOE")

            async with self.session_factory() as db:
                payout = await service.create_payout(
                    db,
                    user_id=self.user_id,
                    amount_ngn=5000,
                    reference="PAYOUT-10025",
                    bank_code="058",
                    bank_name="Guaranty Trust Bank",
                    account_name=enquiry["accountName"],
                    account_number="0123456789",
                    idempotency_key="idem-payout-1",
                )
                self.assertEqual(payout.flow, FiatPaymentFlow.PAYOUT.value)
                self.assertEqual(payout.status, FiatPaymentStatus.PROCESSING.value)
                self.assertEqual(payout.total_debited, "5080.00")
                self.assertEqual(payout.route, "external_bank")

                reconciled = await service.reconcile_payout(db, payout)
                self.assertEqual(reconciled.status, FiatPaymentStatus.COMPLETED.value)
                self.assertEqual(reconciled.provider_reference, "PYT_123")

    async def test_validation_409_failure_and_timeout_retry_idempotency(self) -> None:
        async with aiohttp.ClientSession() as http_session:
            service = FossaPayService(
                api_key="fk_test_key",
                base_url=self.base_url,
                session=http_session,
            )
            async with self.session_factory() as db:
                with self.assertRaises(ValueError):
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn="5000.50",
                        reference="ORDER-BAD-DEC",
                    )

                self.mock_responses[("POST", "/api/v1/checkouts")] = (
                    503,
                    {"message": "Upstream timeout"},
                )
                with self.assertRaises(FossaPayError) as ctx:
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn=2500,
                        reference="ORDER-RETRY-1",
                    )
                self.assertEqual(ctx.exception.status_code, 503)
                first_idem = self.requests[-1]["headers"]["X-Idempotency-Key"]

                # Reusing the same reference with a mismatched idempotency key must fail locally
                with self.assertRaises(ValueError):
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn=2500,
                        reference="ORDER-RETRY-1",
                        idempotency_key="different-key",
                    )

                # Reusing an existing idempotency_key with a new reference must fail locally
                with self.assertRaises(ValueError):
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn=2500,
                        reference="ORDER-NEW-REF",
                        idempotency_key=first_idem,
                    )

                self.mock_responses[("POST", "/api/v1/checkouts")] = (
                    201,
                    {
                        "status": "success",
                        "statusCode": 201,
                        "message": "Created",
                        "data": {
                            "id": str(uuid4()),
                            "reference": "ORDER-RETRY-1",
                            "status": "pending",
                            "amount": "2500.00",
                            "fee": "50.00",
                            "amountPayable": "2550.00",
                            "settlementAmount": "2500.00",
                            "feeBearer": "customer",
                            "currency": "NGN",
                            "account": {
                                "type": "temporary",
                                "bankName": "Sterling Bank",
                                "accountName": "FOSSAPAY CHECKOUT",
                                "accountNumber": "9541382799",
                                "expiresAt": "2026-09-11T10:30:00.000Z",
                            },
                            "customer": None,
                            "metadata": None,
                            "transactionId": None,
                            "providerCheckoutReference": None,
                            "expiresAt": "2026-09-11T10:30:00.000Z",
                            "completedAt": None,
                            "failedAt": None,
                            "reversedAt": None,
                            "createdAt": "2026-09-11T10:00:00.000Z",
                            "updatedAt": "2026-09-11T10:00:00.000Z",
                        },
                    },
                )
                retried = await service.create_checkout(
                    db,
                    user_id=self.user_id,
                    amount_ngn=2500,
                    reference="ORDER-RETRY-1",
                )
                second_idem = self.requests[-1]["headers"]["X-Idempotency-Key"]
                self.assertEqual(first_idem, second_idem)
                self.assertEqual(retried.status, FiatPaymentStatus.PENDING.value)

                # A 409 conflict on a new reference marks it failed and rejects blind reuse
                self.mock_responses[("POST", "/api/v1/checkouts")] = (
                    409,
                    {"message": "Checkout reference already exists for this merchant"},
                )
                with self.assertRaises(FossaPayError) as conflict_ctx:
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn=2500,
                        reference="ORDER-CONFLICT-1",
                    )
                self.assertEqual(conflict_ctx.exception.status_code, 409)
                with self.assertRaises(ValueError):
                    await service.create_checkout(
                        db,
                        user_id=self.user_id,
                        amount_ngn=2500,
                        reference="ORDER-CONFLICT-1",
                    )


if __name__ == "__main__":
    unittest.main()
