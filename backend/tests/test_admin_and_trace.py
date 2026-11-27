import os
import unittest
from datetime import datetime, timedelta, timezone
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

import nacl.signing
import base58
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import app.models  # noqa: F401
from app.models.payment import (
    FiatPayment,
    FiatPaymentFlow,
    FiatPaymentStatus,
    MerchantBankAccount,
    PajOfframpOrder,
    PajOrderStatus,
    PaymentIntent,
    PaymentTraceEvent,
    SettlementTarget,
)
from app.models.payroll import PayrollGroup
from app.models.user import User
from app.routers.auth import create_jwt_token
from app.routers.dashboard import _load_recent_activity, _ngn_expression
from app.services.payment import FossaPayError
from app.services.trace import SEED_ADMIN_ADDRESSES
from core.config import settings
from core.session import get_session
from main import app

SEED_ADMIN_ADDRESS = next(iter(SEED_ADMIN_ADDRESSES))


def _new_wallet_and_sig(challenge_fn) -> tuple[str, str, str]:
    signing_key = nacl.signing.SigningKey.generate()
    address = base58.b58encode(bytes(signing_key.verify_key)).decode("utf-8")
    nonce = challenge_fn(address)
    message = f"Sign this message to login to Veil: {nonce}"
    sig = base58.b58encode(signing_key.sign(message.encode("utf-8")).signature).decode("utf-8")
    return address, message, sig


class AdminAndTraceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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
        self.client.close()
        await self.engine.dispose()

    def _auth_header(self, user: User) -> dict[str, str]:
        token = create_jwt_token(str(user.id), user.address)
        return {"Authorization": f"Bearer {token}"}

    async def _create_user(self, address: str | None = None, *, is_admin: bool = False) -> User:
        async with self.session_factory() as db:
            user = User(
                address=address or base58.b58encode(bytes(nacl.signing.SigningKey.generate().verify_key)).decode("utf-8"),
                is_admin=is_admin,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    async def test_seed_admin_bootstrap_and_admin_management_guards(self) -> None:
        # Unauthenticated hits 401
        self.assertEqual(self.client.get("/v1/admin/overview").status_code, 401)

        # Normal wallet logs in as non-admin and receives 403 on admin routes
        def get_nonce(addr: str) -> str:
            res = self.client.post("/v1/auth/challenge", json={"address": addr})
            self.assertEqual(res.status_code, 200)
            return res.json()["nonce"]

        addr, msg, sig = _new_wallet_and_sig(get_nonce)
        login_res = self.client.post("/v1/auth/login", json={"address": addr, "message": msg, "signature": sig})
        self.assertEqual(login_res.status_code, 200)
        self.assertFalse(login_res.json()["user"]["isAdmin"])
        non_admin_token = login_res.json()["token"]
        self.assertEqual(
            self.client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {non_admin_token}"}).status_code,
            403,
        )

        # Seed admin wallet is promoted on challenge/me even without migration SQL
        seed_challenge = self.client.post("/v1/auth/challenge", json={"address": SEED_ADMIN_ADDRESS})
        self.assertEqual(seed_challenge.status_code, 200)
        async with self.session_factory() as db:
            seed_user = (await db.execute(select(User).where(User.address == SEED_ADMIN_ADDRESS))).scalars().one()
        self.assertTrue(seed_user.is_admin)

        me_res = self.client.get("/v1/auth/me", headers=self._auth_header(seed_user))
        self.assertEqual(me_res.status_code, 200)
        self.assertTrue(me_res.json()["isAdmin"])
        self.assertEqual(me_res.json()["address"], SEED_ADMIN_ADDRESS)

        # Seed admin grants admin to the normal wallet, lists admins, rejects invalid address, cannot revoke seed
        grant_res = self.client.post(
            "/v1/admin/admins",
            json={"address": addr, "note": "Support ops lead"},
            headers=self._auth_header(seed_user),
        )
        self.assertEqual(grant_res.status_code, 201)
        self.assertTrue(grant_res.json()["isAdmin"])

        # Newly promoted admin works immediately
        promoted_me = self.client.get("/v1/auth/me", headers={"Authorization": f"Bearer {non_admin_token}"})
        self.assertTrue(promoted_me.json()["isAdmin"])
        self.assertEqual(
            self.client.get("/v1/admin/admins", headers={"Authorization": f"Bearer {non_admin_token}"}).status_code,
            200,
        )

        # Invalid address rejected
        bad_addr = self.client.post(
            "/v1/admin/admins",
            json={"address": "not-a-valid-solana-address-string"},
            headers=self._auth_header(seed_user),
        )
        self.assertEqual(bad_addr.status_code, 422)

        # Seed admin cannot be revoked; self cannot be revoked
        revoke_seed = self.client.delete(
            f"/v1/admin/admins/{SEED_ADMIN_ADDRESS}",
            headers={"Authorization": f"Bearer {non_admin_token}"},
        )
        self.assertEqual(revoke_seed.status_code, 409)

        revoke_self = self.client.delete(
            f"/v1/admin/admins/{addr}",
            headers={"Authorization": f"Bearer {non_admin_token}"},
        )
        self.assertEqual(revoke_self.status_code, 409)

        # Seed admin revokes secondary admin cleanly
        revoke_res = self.client.delete(
            f"/v1/admin/admins/{addr}",
            headers=self._auth_header(seed_user),
        )
        self.assertEqual(revoke_res.status_code, 200)
        self.assertFalse(revoke_res.json()["isAdmin"])

    async def test_payout_failure_creates_trace_anomaly_and_admin_retry_recovers(self) -> None:
        merchant = await self._create_user()
        admin = await self._create_user(SEED_ADMIN_ADDRESS, is_admin=True)

        async with self.session_factory() as db:
            bank = MerchantBankAccount(
                user_id=merchant.id,
                paj_account_id="paj_acc_1",
                bank_code="999992",
                bank_name="OPay",
                account_number="8012345678",
                account_name="Ada Obi",
                solana_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
                is_default=True,
            )
            db.add(bank)
            await db.commit()
            await db.refresh(bank)

        with (
            patch("app.services.payment_intents.get_rates", new=AsyncMock(return_value={"usdc": Decimal("1500"), "sol": Decimal("220000")})),
            patch("app.routers.payments.FossaPayService.create_checkout", new=AsyncMock(side_effect=self._persist_fake_checkout)),
        ):
            create_res = self.client.post(
                "/v1/payments/intents",
                json={
                    "merchantRef": "ORDER-TRACE-1",
                    "token": "USDC",
                    "amount_ngn": "5000",
                    "recipientAddress": merchant.address,
                    "receiveMode": "public",
                    "settlementTarget": "fiat",
                    "bankAccountId": str(bank.id),
                    "includeFiatCheckout": True,
                },
                headers=self._auth_header(merchant),
            )
            self.assertEqual(create_res.status_code, 200)
            intent_id = create_res.json()["id"]
            checkout_ref = create_res.json()["fiatCheckout"]["reference"]

        # Simulate FossaPay webhook checkout.completed while payout API returns 502 error
        with (
            patch("app.routers.webhook.verify_fossapay_webhook", return_value=True),
            patch("app.routers.payments.FossaPayService.create_payout", new=AsyncMock(side_effect=FossaPayError("Master wallet timeout", status_code=502))),
        ):
            wh = self.client.post(
                "/v1/webhook/fossapay",
                json={
                    "eventId": "evt_1001",
                    "eventType": "checkout.completed",
                    "data": {
                        "checkoutId": "chk_1001",
                        "reference": checkout_ref,
                        "status": "completed",
                        "amount": "5000.00",
                        "settlementAmount": "5000.00",
                    },
                },
            )
            self.assertEqual(wh.status_code, 200)

        # Admin overview + anomaly list immediately catches funded_without_payout + full trace!
        anomalies_res = self.client.get(
            "/v1/admin/flows?status=anomalies",
            headers=self._auth_header(admin),
        )
        self.assertEqual(anomalies_res.status_code, 200)
        items = anomalies_res.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], intent_id)
        self.assertEqual(items[0]["recommendedAction"], "retry_payout")
        self.assertEqual(items[0]["anomalies"][0]["code"], "funded_without_payout")

        detail_res = self.client.get(
            f"/v1/admin/flows/{intent_id}",
            headers=self._auth_header(admin),
        )
        self.assertEqual(detail_res.status_code, 200)
        event_types = [t["eventType"] for t in detail_res.json()["traces"]]
        self.assertIn("intent_created", event_types)
        self.assertIn("fossapay_checkout_created", event_types)
        self.assertIn("fossapay_webhook", event_types)
        self.assertIn("fossapay_checkout_completed", event_types)
        self.assertIn("fossapay_payout_failed", event_types)

        # Now FossaPay recovers -> Admin clicks Retry Payout
        async def fake_completed_payout(_service, db_s, **kw):
            row = FiatPayment(
                user_id=kw["user_id"],
                payment_intent_id=kw["payment_intent_id"],
                flow=FiatPaymentFlow.PAYOUT.value,
                reference=kw["reference"],
                idempotency_key=kw["idempotency_key"],
                fossapay_id="pay_retry_1",
                amount=str(kw["amount_ngn"]),
                settlement_amount=str(kw["amount_ngn"]),
                bank_code=kw["bank_code"],
                bank_name=kw["bank_name"],
                account_number=kw["account_number"],
                account_name=kw["account_name"],
                status=FiatPaymentStatus.COMPLETED.value,
            )
            db_s.add(row)
            await db_s.commit()
            await db_s.refresh(row)
            return row

        with patch("app.routers.payments.FossaPayService.create_payout", new=fake_completed_payout):
            retry_res = self.client.post(
                f"/v1/admin/flows/{intent_id}/retry-payout",
                json={"note": "Retried after FossaPay 502 recovered"},
                headers=self._auth_header(admin),
            )
            self.assertEqual(retry_res.status_code, 200)
            detail = retry_res.json()
            self.assertEqual(detail["settlementStatus"], "settled")
            self.assertEqual(detail["anomalies"], [])

        # Anomaly list is now empty
        after_anomalies = self.client.get(
            "/v1/admin/flows?status=anomalies",
            headers=self._auth_header(admin),
        )
        self.assertEqual(after_anomalies.json()["total"], 0)

    async def _persist_fake_checkout(self, db_s: AsyncSession, **kw) -> FiatPayment:
        row = FiatPayment(
            user_id=kw["user_id"],
            payment_intent_id=kw["payment_intent_id"],
            flow=FiatPaymentFlow.CHECKOUT.value,
            reference=kw["reference"],
            idempotency_key=f"chk:{kw['reference']}",
            fossapay_id=f"fp_{kw['reference']}",
            amount=str(kw["amount_ngn"]),
            bank_name="Wema Bank",
            account_number="9988776655",
            account_name="Veil Checkout",
            status=FiatPaymentStatus.PENDING.value,
        )
        db_s.add(row)
        await db_s.commit()
        await db_s.refresh(row)
        return row

    async def test_expired_intent_pre_expiry_tx_reconciles_and_direct_crypto_flags_accurately(self) -> None:
        merchant = await self._create_user()
        admin = await self._create_user(SEED_ADMIN_ADDRESS, is_admin=True)
        payer_sig = "5" * 88
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async with self.session_factory() as db:
            bank = MerchantBankAccount(
                user_id=merchant.id,
                paj_account_id="paj_acc_2",
                bank_code="999992",
                bank_name="OPay",
                account_number="8099998888",
                account_name="Chidi",
                solana_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
                is_default=True,
            )
            db.add(bank)
            await db.commit()
            await db.refresh(bank)

            intent = PaymentIntent(
                user_id=merchant.id,
                merchant_ref="EXP-PRE-1",
                mint=settings.USDC_MINT,
                amount_atomic="10000000",
                amount_ngn="15000",
                rate_ngn_per_token="1500",
                recipient_address=merchant.address,
                receive_mode="public",
                settlement_target=SettlementTarget.FIAT.value,
                bank_account_id=bank.id,
                status="failed",
                failure_reason="expired",
                created_at=now - timedelta(minutes=40),
                updated_at=now - timedelta(minutes=5),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            db.add(intent)
            await db.commit()
            await db.refresh(intent)

        # Dry-run verify-signature against mocked on-chain verification on an expired intent
        with patch("app.routers.admin.verify_transfer", new=AsyncMock(return_value=True)):
            dry_res = self.client.post(
                f"/v1/admin/flows/{intent.id}/verify-signature",
                json={"signature": payer_sig, "rail": "direct", "dryRun": True},
                headers=self._auth_header(admin),
            )
            self.assertEqual(dry_res.status_code, 200)
            self.assertTrue(dry_res.json()["matchedWithMemo"])
            self.assertFalse(dry_res.json()["applied"])

            apply_res = self.client.post(
                f"/v1/admin/flows/{intent.id}/verify-signature",
                json={"signature": payer_sig, "rail": "direct", "dryRun": False, "note": "Customer sent direct to merchant"},
                headers=self._auth_header(admin),
            )
            self.assertEqual(apply_res.status_code, 200)
            self.assertTrue(apply_res.json()["applied"])
            flow = apply_res.json()["flow"]
            self.assertEqual(flow["intentStatus"], "funded")
            self.assertEqual(flow["paidVia"], "crypto")
            self.assertEqual(flow["settlementStatus"], "settled")
            self.assertEqual(flow["anomalies"][0]["code"], "direct_crypto_on_fiat_intent")

        # Merchant dashboard reflects accurate paidVia="crypto" and "settled" rather than stuck "settling"
        async with self.session_factory() as db:
            activity = await _load_recent_activity(db, merchant.id, _ngn_expression())
        act = activity[0]
        self.assertEqual(act["paid_via"], "crypto")
        self.assertEqual(act["settlement_status"], "settled")

    async def test_admin_payroll_and_unlinked_fiat_endpoints(self) -> None:
        merchant = await self._create_user()
        admin = await self._create_user(SEED_ADMIN_ADDRESS, is_admin=True)

        async with self.session_factory() as db:
            group = PayrollGroup(
                user_id=merchant.id,
                employer_ref="PAY-ADMIN-1",
                title="March Ops",
                token="SOL",
                release_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
                recipients_json='[{"name":"Tunde","walletAddress":"11111111111111111111111111111111","amountNgn":"50000","amountAtomic":"500000000"}]',
                status="locked",
                vault_signature="4" * 88,
            )
            standalone = FiatPayment(
                user_id=merchant.id,
                payment_intent_id=None,
                flow=FiatPaymentFlow.PAYOUT.value,
                reference="STANDALONE-PAYOUT-1",
                idempotency_key="standalone-1",
                amount="25000",
                bank_name="GTBank",
                account_number="0123456789",
                account_name="Vendor",
                status=FiatPaymentStatus.PROCESSING.value,
            )
            db.add(group)
            db.add(standalone)
            await db.commit()

        payroll_res = self.client.get("/v1/admin/payroll", headers=self._auth_header(admin))
        self.assertEqual(payroll_res.status_code, 200)
        self.assertEqual(payroll_res.json()["total"], 1)
        self.assertEqual(payroll_res.json()["items"][0]["totalAmountNgn"], "50000")

        unlinked_res = self.client.get("/v1/admin/unlinked-fiat", headers=self._auth_header(admin))
        self.assertEqual(unlinked_res.status_code, 200)
        self.assertEqual(unlinked_res.json()["total"], 1)
        self.assertEqual(unlinked_res.json()["items"][0]["reference"], "STANDALONE-PAYOUT-1")


if __name__ == "__main__":
    unittest.main()
