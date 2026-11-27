import hashlib
import hmac
import json
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

import httpx
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401
from app.models.payment import PaymentIntent
from app.models.user import User
from app.models.whatsapp import WhatsAppLink, WhatsAppSetupToken
from app.routers.auth import create_jwt_token
from app.routers.whatsapp import _send_whatsapp
from app.services.whatsapp_linking import _graph_phone_cache
from core.config import settings
from core.session import get_session
from main import app


APP_SECRET = "test-meta-app-secret"


class WhatsAppWebhookTests(unittest.IsolatedAsyncioTestCase):
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

    def _payload(self, text: str, message_id: str) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "2348012345678",
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

    def _post_signed_payload(self, payload: dict, secret: str = APP_SECRET):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/v1/whatsapp/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={signature}",
            },
        )

    def _payment_intent(self, *, receive_mode: str, allow_fiat_checkout: bool) -> PaymentIntent:
        return PaymentIntent(
            id=uuid4(),
            user_id=self.user.id,
            merchant_ref="WhatsApp payment",
            mint=settings.USDC_MINT,
            amount_atomic="1000000",
            amount_ngn="5000",
            rate_ngn_per_token="1500",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            recipient_address=self.user.address,
            receive_mode=receive_mode,
            allow_fiat_checkout=allow_fiat_checkout,
            memo="lunch",
        )

    def test_meta_webhook_verification_returns_plain_text_challenge(self) -> None:
        with patch.object(settings, "WHATSAPP_VERIFY_TOKEN", "test-verify-token"):
            response = self.client.get(
                "/v1/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "test-verify-token",
                    "hub.challenge": "12345",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(response.text, "12345")

    def test_meta_webhook_verification_rejects_mismatched_token(self) -> None:
        with patch.object(settings, "WHATSAPP_VERIFY_TOKEN", "expected-token"):
            response = self.client.get(
                "/v1/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong-token",
                    "hub.challenge": "12345",
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_post_rejects_invalid_meta_signature(self) -> None:
        payload = self._payload("help", "wamid-invalid-signature")
        body = json.dumps(payload).encode()

        with patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET):
            response = self.client.post(
                "/v1/whatsapp/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_post_requires_meta_app_secret(self) -> None:
        with patch.object(settings, "WHATSAPP_APP_SECRET", None):
            response = self._post_signed_payload(self._payload("help", "wamid-no-secret"))

        self.assertEqual(response.status_code, 503)

    async def test_sender_uses_meta_graph_api(self) -> None:
        with (
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch("app.routers.whatsapp.httpx.AsyncClient") as async_client,
        ):
            post = AsyncMock(
                return_value=httpx.Response(
                    200,
                    json={"messages": [{"id": "wamid-out"}]},
                    request=httpx.Request(
                        "POST",
                        "https://graph.facebook.com/v26.0/123456789/messages",
                    ),
                )
            )
            async_client.return_value.__aenter__.return_value.post = post

            await _send_whatsapp("+2348012345678", "Hello")

        post.assert_awaited_once_with(
            "https://graph.facebook.com/v26.0/123456789/messages",
            headers={
                "Authorization": "Bearer test-access-token",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": "2348012345678",
                "type": "text",
                "text": {"body": "Hello"},
            },
        )

    async def test_sender_raises_when_meta_rejects_message(self) -> None:
        with (
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch("app.routers.whatsapp.httpx.AsyncClient") as async_client,
        ):
            post = AsyncMock(
                return_value=httpx.Response(
                    500,
                    json={"error": {"message": "temporary error"}},
                    request=httpx.Request(
                        "POST",
                        "https://graph.facebook.com/v26.0/123456789/messages",
                    ),
                )
            )
            async_client.return_value.__aenter__.return_value.post = post

            with self.assertRaises(httpx.HTTPStatusError):
                await _send_whatsapp("+2348012345678", "Hello")

    async def test_failed_send_is_retried_without_creating_another_payment(self) -> None:
        payload = self._payload("5000 for lunch", "wamid-retry-send")
        intent = self._payment_intent(receive_mode="public", allow_fiat_checkout=True)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch(
                "app.routers.whatsapp._send_whatsapp",
                new=AsyncMock(side_effect=[RuntimeError("temporary send failure"), None]),
            ) as send_reply,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            failed_response = self._post_signed_payload(payload)
            retry_response = self._post_signed_payload(payload)

        self.assertEqual(failed_response.status_code, 503)
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(send_reply.await_count, 2)
        self.assertEqual(
            send_reply.await_args_list[0].kwargs["body"],
            send_reply.await_args_list[1].kwargs["body"],
        )
        create_intent.assert_awaited_once()

    async def test_checkout_message_uses_meta_payload_and_deduplicates(self) -> None:
        payload = self._payload("5000 for lunch", "wamid-meta-checkout")
        intent = self._payment_intent(receive_mode="public", allow_fiat_checkout=True)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch(
                "app.routers.whatsapp._send_whatsapp",
                new=AsyncMock(),
            ) as send_reply,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            response = self._post_signed_payload(payload)
            duplicate_response = self._post_signed_payload(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        send_reply.assert_awaited_once()
        self.assertEqual(send_reply.await_args.kwargs["to_number"], "2348012345678")
        self.assertIn(f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}", send_reply.await_args.kwargs["body"])
        self.assertIn("Checkout link:", send_reply.await_args.kwargs["body"])
        create_intent.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["token"], "USDC")
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "public")
        self.assertTrue(create_intent.await_args.kwargs["allow_fiat_checkout"])

    async def test_vendor_can_request_private_crypto_only_checkout(self) -> None:
        payload = self._payload(
            "5000 for lunch private crypto only",
            "wamid-meta-private-crypto-only",
        )
        intent = self._payment_intent(receive_mode="private", allow_fiat_checkout=False)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch(
                "app.routers.whatsapp._send_whatsapp",
                new=AsyncMock(),
            ) as send_reply,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            response = self._post_signed_payload(payload)

        self.assertEqual(response.status_code, 200)
        send_reply.assert_awaited_once()
        self.assertIn("private USDC only", send_reply.await_args.kwargs["body"])
        self.assertIn(f"{settings.FRONTEND_URL.rstrip('/')}/pay/{intent.id}", send_reply.await_args.kwargs["body"])
        create_intent.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "private")
        self.assertFalse(create_intent.await_args.kwargs["allow_fiat_checkout"])

    def _auth_headers(self, user: User) -> dict[str, str]:
        token = create_jwt_token(str(user.id), user.address)
        return {"Authorization": f"Bearer {token}"}

    async def test_unlinked_inbound_message_sends_setup_tracking_link_and_completes_setup(self) -> None:
        unlinked_from = "2348099998888"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": unlinked_from,
                                        "id": "wamid-unlinked-first",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
        ):
            response = self._post_signed_payload(payload)

        self.assertEqual(response.status_code, 200)
        send_reply.assert_awaited_once()
        reply_body = send_reply.await_args.kwargs["body"]
        prefix = f"{settings.FRONTEND_URL.rstrip('/')}/settings?whatsapp_setup="
        self.assertIn(prefix, reply_body)
        setup_token = reply_body.split(prefix, 1)[1].split()[0]

        async with self.session_factory() as db:
            new_merchant = User(address=str(Pubkey.new_unique()))
            db.add(new_merchant)
            await db.commit()
            await db.refresh(new_merchant)

        headers = self._auth_headers(new_merchant)
        preview = self.client.get(f"/v1/whatsapp/setup/{setup_token}", headers=headers)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["phone_masked"], "+234••••••8888")
        self.assertFalse(preview.json()["already_linked_to_current_user"])
        self.assertFalse(preview.json()["already_linked_to_other_account"])

        with (
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch("app.routers.whatsapp_accounts._send_whatsapp", new=AsyncMock()) as notify_reply,
        ):
            complete = self.client.post(
                "/v1/whatsapp/setup/complete",
                json={"token": setup_token},
                headers=headers,
            )

        self.assertEqual(complete.status_code, 200)
        self.assertTrue(complete.json()["ok"])
        self.assertTrue(complete.json()["notified_whatsapp"])
        self.assertEqual(complete.json()["phone_masked"], "+234••••••8888")
        notify_reply.assert_awaited_once()
        self.assertEqual(notify_reply.await_args.kwargs["to_number"], "+2348099998888")
        self.assertIn("Your WhatsApp is now linked to", notify_reply.await_args.kwargs["body"])

        status_resp = self.client.get("/v1/whatsapp/status", headers=headers)
        self.assertEqual(status_resp.status_code, 200)
        self.assertTrue(status_resp.json()["linked"])
        self.assertEqual(status_resp.json()["phone_masked"], "+234••••••8888")

        replay_preview = self.client.get(f"/v1/whatsapp/setup/{setup_token}", headers=headers)
        self.assertEqual(replay_preview.status_code, 410)
        replay_complete = self.client.post(
            "/v1/whatsapp/setup/complete",
            json={"token": setup_token},
            headers=headers,
        )
        self.assertEqual(replay_complete.status_code, 410)

    async def test_setup_completion_succeeds_when_whatsapp_notification_fails_and_rejects_expired(self) -> None:
        async with self.session_factory() as db:
            db.add(
                WhatsAppSetupToken(
                    token="valid-setup-tok",
                    phone_e164="+2348077776666",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
            )
            db.add(
                WhatsAppSetupToken(
                    token="expired-setup-tok",
                    phone_e164="+2348077776666",
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            await db.commit()

        headers = self._auth_headers(self.user)
        expired_resp = self.client.get("/v1/whatsapp/setup/expired-setup-tok", headers=headers)
        self.assertEqual(expired_resp.status_code, 410)

        with (
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "test-access-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "123456789"),
            patch(
                "app.routers.whatsapp_accounts._send_whatsapp",
                new=AsyncMock(side_effect=RuntimeError("meta unreachable")),
            ),
        ):
            complete = self.client.post(
                "/v1/whatsapp/setup/complete",
                json={"token": "valid-setup-tok"},
                headers=headers,
            )

        self.assertEqual(complete.status_code, 200)
        self.assertTrue(complete.json()["ok"])
        self.assertFalse(complete.json()["notified_whatsapp"])

    async def test_link_code_returns_code_without_business_number_and_uses_graph_api_fallback(self) -> None:
        headers = self._auth_headers(self.user)

        with (
            patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", None),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", None),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", None),
        ):
            no_number_resp = self.client.post("/v1/whatsapp/link-code", headers=headers)

        self.assertEqual(no_number_resp.status_code, 200)
        body = no_number_resp.json()
        self.assertEqual(len(body["code"]), 6)
        self.assertIsNone(body["join_url"])
        self.assertIsNone(body["link_url"])

        with (
            patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", None),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", "graph-token"),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", "987654321"),
            patch("app.services.whatsapp_linking.httpx.AsyncClient") as async_client,
        ):
            get_mock = AsyncMock(
                return_value=httpx.Response(
                    200,
                    json={"id": "987654321", "display_phone_number": "+234 800 123 4567"},
                    request=httpx.Request(
                        "GET",
                        "https://graph.facebook.com/v26.0/987654321",
                    ),
                )
            )
            async_client.return_value.__aenter__.return_value.get = get_mock
            graph_resp = self.client.post("/v1/whatsapp/link-code", headers=headers)

        self.assertEqual(graph_resp.status_code, 200)
        graph_body = graph_resp.json()
        self.assertEqual(graph_body["join_url"], "https://wa.me/2348001234567")
        self.assertEqual(
            graph_body["link_url"],
            f"https://wa.me/2348001234567?text=link%20{graph_body['code']}",
        )
        get_mock.assert_awaited_once()

    async def test_consuming_link_code_invalidates_pending_setup_tokens(self) -> None:
        async with self.session_factory() as db:
            other_user = User(address=str(Pubkey.new_unique()))
            db.add(other_user)
            db.add(
                WhatsAppSetupToken(
                    token="pending-tok-1",
                    phone_e164="+2348055554444",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
            )
            await db.commit()
            await db.refresh(other_user)

        other_headers = self._auth_headers(other_user)
        with (
            patch.object(settings, "WHATSAPP_BUSINESS_PHONE_NUMBER", None),
            patch.object(settings, "WHATSAPP_ACCESS_TOKEN", None),
            patch.object(settings, "WHATSAPP_PHONE_NUMBER_ID", None),
        ):
            code_resp = self.client.post("/v1/whatsapp/link-code", headers=other_headers)
        self.assertEqual(code_resp.status_code, 200)
        code = code_resp.json()["code"]

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "2348055554444",
                                        "id": "wamid-consume-code-1",
                                        "type": "text",
                                        "text": {"body": f"link {code}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
        ):
            webhook_resp = self._post_signed_payload(payload)

        self.assertEqual(webhook_resp.status_code, 200)
        self.assertIn("Your WhatsApp is now linked to", send_reply.await_args.kwargs["body"])
        replay_setup = self.client.get("/v1/whatsapp/setup/pending-tok-1", headers=self._auth_headers(self.user))
        self.assertEqual(replay_setup.status_code, 410)

    async def test_setup_preview_flags_number_linked_to_other_account(self) -> None:
        async with self.session_factory() as db:
            other_user = User(address=str(Pubkey.new_unique()))
            db.add(other_user)
            db.add(
                WhatsAppSetupToken(
                    token="reassign-tok-1",
                    phone_e164="+2348012345678",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
            )
            await db.commit()
            await db.refresh(other_user)

        other_headers = self._auth_headers(other_user)
        preview = self.client.get("/v1/whatsapp/setup/reassign-tok-1", headers=other_headers)
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["already_linked_to_other_account"])
        self.assertFalse(preview.json()["already_linked_to_current_user"])

    async def test_regex_matched_message_skips_gemini_fallback(self) -> None:
        payload = self._payload("5000 for lunch", "wamid-regex-fastpath")
        intent = self._payment_intent(receive_mode="public", allow_fiat_checkout=True)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()),
            patch("app.routers.whatsapp.create_payment_intent", new=AsyncMock(return_value=intent)),
            patch(
                "app.routers.whatsapp.parse_message_with_gemini",
                new=AsyncMock(),
            ) as gemini_parse,
        ):
            response = self._post_signed_payload(payload)

        self.assertEqual(response.status_code, 200)
        gemini_parse.assert_not_awaited()

    async def test_fallback_message_uses_gemini_to_create_checkout_link(self) -> None:
        payload = self._payload(
            "abeg bill Chidi fifteen thousand naira for sneakers private crypto only",
            "wamid-gemini-create-link",
        )
        intent = self._payment_intent(receive_mode="private", allow_fiat_checkout=False)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch.object(settings, "WHATSAPP_PAYMENT_METHODS", "usdc,fossapay"),
            patch.object(settings, "WHATSAPP_PRIVATE_PAYMENTS", False),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
            patch(
                "app.routers.whatsapp.parse_message_with_gemini",
                new=AsyncMock(
                    return_value={
                        "intent": "create_link",
                        "code": None,
                        "amount_ngn": Decimal("15000"),
                        "memo": "Chidi sneakers",
                        "amount_error": None,
                        "receive_mode": "private",
                        "crypto_only": True,
                    }
                ),
            ) as gemini_parse,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            response = self._post_signed_payload(payload)

        self.assertEqual(response.status_code, 200)
        gemini_parse.assert_awaited_once_with(
            "abeg bill Chidi fifteen thousand naira for sneakers private crypto only",
            awaiting_amount=False,
        )
        create_intent.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["amount_ngn"], Decimal("15000"))
        self.assertEqual(create_intent.await_args.kwargs["memo"], "Chidi sneakers")
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "private")
        self.assertFalse(create_intent.await_args.kwargs["allow_fiat_checkout"])
        self.assertIn("private USDC only", send_reply.await_args.kwargs["body"])

    async def test_fallback_message_uses_gemini_for_recent_payments_and_awaiting_amount(self) -> None:
        recent_payload = self._payload(
            "how much people don pay me recently?",
            "wamid-gemini-recent",
        )
        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
            patch(
                "app.routers.whatsapp.parse_message_with_gemini",
                new=AsyncMock(
                    return_value={
                        "intent": "recent_payments",
                        "code": None,
                        "amount_ngn": None,
                        "memo": None,
                        "amount_error": None,
                        "receive_mode": None,
                        "crypto_only": False,
                    }
                ),
            ),
        ):
            recent_resp = self._post_signed_payload(recent_payload)

        self.assertEqual(recent_resp.status_code, 200)
        self.assertIn("No payments yet.", send_reply.await_args.kwargs["body"])

        ask_payload = self._payload("link for generator", "wamid-gemini-draft")
        amount_payload = self._payload("twenty thousand naira", "wamid-gemini-amount")
        intent = self._payment_intent(receive_mode="public", allow_fiat_checkout=True)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply2,
            patch(
                "app.routers.whatsapp.parse_message_with_gemini",
                new=AsyncMock(
                    side_effect=[
                        {
                            "intent": "create_link",
                            "code": None,
                            "amount_ngn": None,
                            "memo": "generator",
                            "amount_error": None,
                            "receive_mode": None,
                            "crypto_only": False,
                        },
                        {
                            "intent": "create_link",
                            "code": None,
                            "amount_ngn": Decimal("20000"),
                            "memo": None,
                            "amount_error": None,
                            "receive_mode": None,
                            "crypto_only": False,
                        },
                    ]
                ),
            ) as gemini_amount,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            ask_resp = self._post_signed_payload(ask_payload)
            amount_resp = self._post_signed_payload(amount_payload)

        self.assertEqual(ask_resp.status_code, 200)
        self.assertEqual(amount_resp.status_code, 200)
        self.assertEqual(gemini_amount.await_count, 2)
        self.assertEqual(
            gemini_amount.await_args_list[1].args,
            ("twenty thousand naira",),
        )
        self.assertEqual(gemini_amount.await_args_list[1].kwargs, {"awaiting_amount": True})
        self.assertEqual(create_intent.await_args.kwargs["amount_ngn"], Decimal("20000"))
        self.assertEqual(create_intent.await_args.kwargs["memo"], "generator")
        self.assertIn("Checkout link:", send_reply2.await_args.kwargs["body"])

    async def test_word_amount_with_link_keyword_uses_gemini(self) -> None:
        payload = self._payload(
            "Abeg collect twenty five thousand five hundred naira for shoes private crypto only",
            "wamid-gemini-word-amount-keyword",
        )
        intent = self._payment_intent(receive_mode="private", allow_fiat_checkout=False)

        with (
            patch.object(settings, "WHATSAPP_APP_SECRET", APP_SECRET),
            patch("app.routers.whatsapp._send_whatsapp", new=AsyncMock()) as send_reply,
            patch(
                "app.routers.whatsapp.parse_message_with_gemini",
                new=AsyncMock(
                    return_value={
                        "intent": "create_link",
                        "code": None,
                        "amount_ngn": Decimal("25500"),
                        "memo": "shoes",
                        "amount_error": None,
                        "receive_mode": None,
                        "crypto_only": False,
                    }
                ),
            ) as gemini_parse,
            patch(
                "app.routers.whatsapp.create_payment_intent",
                new=AsyncMock(return_value=intent),
            ) as create_intent,
        ):
            resp = self._post_signed_payload(payload)

        self.assertEqual(resp.status_code, 200)
        gemini_parse.assert_awaited_once()
        self.assertEqual(create_intent.await_args.kwargs["amount_ngn"], Decimal("25500"))
        self.assertEqual(create_intent.await_args.kwargs["memo"], "shoes")
        self.assertEqual(create_intent.await_args.kwargs["receive_mode"], "private")
        self.assertFalse(create_intent.await_args.kwargs["allow_fiat_checkout"])
        self.assertIn("private USDC only", send_reply.await_args.kwargs["body"])


if __name__ == "__main__":
    unittest.main()
