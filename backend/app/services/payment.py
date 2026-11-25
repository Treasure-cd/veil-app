import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4

import aiohttp
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.payment import (
    FiatPayment,
    FiatPaymentFlow,
    FiatPaymentStatus,
    FossaPayWebhookEvent,
    utc_now,
    utc_now_aware,
)
from core.config import settings

REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
TERMINAL_STATUSES = {
    FiatPaymentStatus.COMPLETED.value,
    FiatPaymentStatus.FAILED.value,
    FiatPaymentStatus.EXPIRED.value,
    FiatPaymentStatus.REVERSED.value,
}
CHECKOUT_EVENTS = {
    "checkout.completed",
    "checkout.failed",
    "checkout.expired",
    "checkout.reversed",
}
PAYOUT_EVENTS = {
    "payout.completed",
    "payout.failed",
    "payout.reversed",
}


class FossaPayError(Exception):
    """Raised when a FossaPay API request fails or returns an error payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.payload = payload


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_reference(reference: str) -> str:
    if not REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError(
            "reference must be 1-100 characters matching ^[A-Za-z0-9._:-]+$"
        )
    return reference


def _validate_ngn_integer_amount(amount_ngn: int | Decimal | str) -> int:
    """Validate that an NGN amount is a positive whole-Naira integer."""
    if isinstance(amount_ngn, bool):
        raise ValueError("amount_ngn must be a positive whole-NGN integer")
    if isinstance(amount_ngn, int):
        amount = amount_ngn
    else:
        dec = Decimal(str(amount_ngn))
        if not dec.is_finite() or dec != dec.to_integral_value():
            raise ValueError("amount_ngn must be a whole-NGN integer (no kobo decimals)")
        amount = int(dec)
    if amount < 1:
        raise ValueError("amount_ngn must be at least 1 NGN")
    return amount


def _apply_common_fields(
    payment: FiatPayment,
    data: Mapping[str, Any],
    *,
    id_key: str,
    provider_ref_keys: tuple[str, ...],
) -> None:
    raw_id = data.get(id_key)
    if raw_id:
        payment.fossapay_id = str(raw_id)
    if data.get("transactionId"):
        payment.transaction_id = str(data["transactionId"])
    for ref_key in provider_ref_keys:
        if data.get(ref_key):
            payment.provider_reference = str(data[ref_key])
            break

    if data.get("amount") is not None:
        payment.amount = str(data["amount"])
    if data.get("fee") is not None:
        payment.fee = str(data["fee"])
    if isinstance(data.get("metadata"), Mapping):
        payment.metadata_json = json.dumps(data["metadata"])

    new_status = data.get("status")
    if new_status and (
        payment.status not in TERMINAL_STATUSES or new_status in TERMINAL_STATUSES
    ):
        payment.status = str(new_status)

    payment.completed_at = _parse_iso_datetime(data.get("completedAt")) or payment.completed_at
    payment.failed_at = _parse_iso_datetime(data.get("failedAt")) or payment.failed_at
    payment.reversed_at = _parse_iso_datetime(data.get("reversedAt")) or payment.reversed_at
    payment.updated_at = utc_now()


def _apply_checkout_data(payment: FiatPayment, data: Mapping[str, Any]) -> None:
    _apply_common_fields(
        payment,
        data,
        id_key="checkoutId" if "checkoutId" in data else "id",
        provider_ref_keys=("providerCheckoutReference", "providerReference"),
    )
    if data.get("amountPayable") is not None:
        payment.amount_payable = str(data["amountPayable"])
    if data.get("settlementAmount") is not None:
        payment.settlement_amount = str(data["settlementAmount"])
    if data.get("feeBearer") is not None:
        payment.fee_bearer = str(data["feeBearer"])
    split = data.get("split")
    if isinstance(split, Mapping) and split.get("code"):
        payment.split_code = str(split["code"])

    account = data.get("account")
    if isinstance(account, Mapping):
        payment.account_type = account.get("type") or payment.account_type
        payment.bank_name = account.get("bankName") or payment.bank_name
        payment.account_name = account.get("accountName") or payment.account_name
        payment.account_number = account.get("accountNumber") or payment.account_number
    elif data.get("accountType") is not None:
        payment.account_type = str(data["accountType"])

    if data.get("paymentOutcome") is not None:
        payment.payment_outcome = str(data["paymentOutcome"])
        payment.failure_reason = str(data["paymentOutcome"])
    if data.get("receivedAmount") is not None:
        payment.received_amount = str(data["receivedAmount"])

    payment.expires_at = _parse_iso_datetime(data.get("expiresAt")) or payment.expires_at


def _apply_payout_data(payment: FiatPayment, data: Mapping[str, Any]) -> None:
    _apply_common_fields(
        payment,
        data,
        id_key="payoutId",
        provider_ref_keys=("providerReference",),
    )
    if data.get("route") is not None:
        payment.route = str(data["route"])
    if data.get("totalDebited") is not None:
        payment.total_debited = str(data["totalDebited"])

    recipient = data.get("recipient")
    if isinstance(recipient, Mapping):
        payment.bank_code = recipient.get("bankCode") or payment.bank_code
        payment.bank_name = recipient.get("bankName") or payment.bank_name
        payment.account_name = recipient.get("accountName") or payment.account_name
        payment.account_number = recipient.get("accountNumber") or payment.account_number


def verify_fossapay_webhook(
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    secret: str | None = None,
) -> bool:
    """Verify FossaPay HMAC-SHA256 over JSON.stringify(body.data) preserving key order."""
    webhook_secret = secret if secret is not None else settings.FOSSAPAY_WEBHOOK_SECRET
    data = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(data, Mapping) or not webhook_secret:
        return False

    signature = ""
    for key, value in headers.items():
        if key.lower() == "x-fossapay-signature":
            signature = str(value or "")
            break
    if not signature:
        return False

    serialized_data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        serialized_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


class FossaPayService:
    """Async client and persistence layer for FossaPay NGN Checkouts and Payouts."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key or settings.FOSSAPAY_API_KEY
        self.base_url = (base_url or settings.FOSSAPAY_BASE_URL).rstrip("/")
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        if idempotency_key is not None:
            headers["X-Idempotency-Key"] = idempotency_key

        url = f"{self.base_url}{path}"

        async def _execute(client: aiohttp.ClientSession) -> dict[str, Any]:
            try:
                async with client.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                ) as response:
                    text = await response.text()
                    try:
                        parsed = json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        parsed = {"message": text}

                    if response.status >= 400:
                        msg = (
                            parsed.get("message")
                            or parsed.get("error")
                            or f"FossaPay request failed with status {response.status}"
                        )
                        raise FossaPayError(
                            str(msg),
                            status_code=response.status,
                            code=parsed.get("code"),
                            payload=parsed if isinstance(parsed, dict) else None,
                        )
                    return parsed
            except aiohttp.ClientError as exc:
                raise FossaPayError(
                    f"FossaPay network error: {exc}",
                    status_code=503,
                ) from exc

        if self._session is not None:
            return await _execute(self._session)

        async with aiohttp.ClientSession(timeout=self._timeout) as client:
            return await _execute(client)

    async def _get_or_create_payment(
        self,
        db: AsyncSession,
        *,
        flow: FiatPaymentFlow,
        reference: str,
        idempotency_key: str | None,
        defaults: dict[str, Any],
    ) -> tuple[FiatPayment, bool]:
        """Return an existing FiatPayment for reference or persist a new one before network I/O."""
        existing = (
            await db.execute(
                select(FiatPayment).where(FiatPayment.reference == reference)
            )
        ).scalars().first()
        if existing:
            if existing.user_id != defaults["user_id"]:
                raise ValueError("Reference is already in use")
            if existing.flow != flow.value:
                raise ValueError(
                    f"Reference already belongs to a {existing.flow} payment"
                )
            if existing.fossapay_id:
                return existing, True
            if existing.status in TERMINAL_STATUSES:
                raise ValueError(
                    f"Reference '{reference}' already terminated with status '{existing.status}'; use a new reference"
                )
            if idempotency_key and idempotency_key != existing.idempotency_key:
                raise ValueError(
                    "idempotency_key does not match the existing pending payment for this reference"
                )
            return existing, False

        if idempotency_key:
            key_in_use = (
                await db.execute(
                    select(FiatPayment).where(
                        FiatPayment.idempotency_key == idempotency_key
                    )
                )
            ).scalars().first()
            if key_in_use:
                raise ValueError(
                    "idempotency_key has already been used for another payment"
                )

        key = idempotency_key or str(uuid4())
        payment = FiatPayment(
            flow=flow.value,
            reference=reference,
            idempotency_key=key,
            **defaults,
        )
        db.add(payment)
        # Persist reference + idempotency_key upfront so ambiguous timeouts can safely replay.
        await db.commit()
        await db.refresh(payment)
        return payment, False

    async def _mark_client_failure(
        self, db: AsyncSession, payment: FiatPayment, message: str
    ) -> None:
        payment.status = FiatPaymentStatus.FAILED.value
        payment.failure_reason = message
        payment.failed_at = utc_now_aware()
        payment.updated_at = utc_now()
        db.add(payment)
        await db.commit()

    async def _find_payment_for_webhook(
        self,
        db: AsyncSession,
        *,
        fossapay_id: str | None,
        reference: str | None,
    ) -> Optional[FiatPayment]:
        if fossapay_id:
            payment = (
                await db.execute(
                    select(FiatPayment).where(FiatPayment.fossapay_id == str(fossapay_id))
                )
            ).scalars().first()
            if payment is not None:
                return payment
        if reference:
            return (
                await db.execute(
                    select(FiatPayment).where(FiatPayment.reference == str(reference))
                )
            ).scalars().first()
        return None

    async def get_supported_banks(self) -> list[dict[str, Any]]:
        res = await self._request("GET", "/api/v1/transfers/fiat/banks")
        return list(res.get("data") or [])

    async def verify_bank_account(
        self, *, bank_code: str, account_number: str
    ) -> dict[str, Any]:
        res = await self._request(
            "POST",
            "/api/v1/transfers/fiat/bank-name-enquiry",
            json_body={"bankCode": bank_code, "accountNumber": account_number},
        )
        return dict(res["data"])

    async def calculate_transfer_fee(self, *, amount_ngn: int | Decimal) -> dict[str, Any]:
        amount = Decimal(str(amount_ngn))
        if not amount.is_finite() or amount < Decimal("0.01"):
            raise ValueError("amount_ngn must be at least 0.01")
        res = await self._request(
            "GET",
            "/api/v1/transfers/fiat/calculate-fee",
            params={"amount": str(amount)},
        )
        return dict(res["data"])

    async def get_master_ngn_wallet(self) -> dict[str, Any]:
        res = await self._request("GET", "/api/v1/wallets/fiat/master")
        return dict(res["data"])

    async def create_checkout(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        amount_ngn: int | Decimal | str,
        reference: str,
        fee_bearer: str = "customer",
        payment_intent_id: UUID | None = None,
        customer: dict[str, str] | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        split_code: str | None = None,
        idempotency_key: str | None = None,
    ) -> FiatPayment:
        """Create a 30-minute FossaPay NGN checkout wallet and persist FiatPayment."""
        amount = _validate_ngn_integer_amount(amount_ngn)
        _validate_reference(reference)
        if fee_bearer not in ("customer", "merchant"):
            raise ValueError("fee_bearer must be 'customer' or 'merchant'")

        payment, already_created = await self._get_or_create_payment(
            db,
            flow=FiatPaymentFlow.CHECKOUT,
            reference=reference,
            idempotency_key=idempotency_key,
            defaults={
                "user_id": user_id,
                "payment_intent_id": payment_intent_id,
                "amount": str(amount),
                "fee_bearer": fee_bearer,
                "split_code": split_code,
                "metadata_json": json.dumps(metadata) if metadata is not None else None,
                "description": description,
                "status": FiatPaymentStatus.PENDING.value,
            },
        )
        if already_created:
            return payment

        body: dict[str, Any] = {
            "amount": amount,
            "currency": "NGN",
            "reference": reference,
            "feeBearer": fee_bearer,
        }
        if customer is not None:
            body["customer"] = customer
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        if split_code is not None:
            body["splitCode"] = split_code

        try:
            res = await self._request(
                "POST",
                "/api/v1/checkouts",
                json_body=body,
                idempotency_key=payment.idempotency_key,
            )
        except FossaPayError as exc:
            if 400 <= exc.status_code < 500:
                await self._mark_client_failure(db, payment, exc.message)
            raise

        _apply_checkout_data(payment, res["data"])
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    async def reconcile_checkout(
        self, db: AsyncSession, payment: FiatPayment
    ) -> FiatPayment:
        """Fetch the latest checkout status from FossaPay by ID or reference."""
        if payment.flow != FiatPaymentFlow.CHECKOUT.value:
            raise ValueError("Payment is not a checkout record")
        path = (
            f"/api/v1/checkouts/{payment.fossapay_id}"
            if payment.fossapay_id
            else f"/api/v1/checkouts/reference/{payment.reference}"
        )
        res = await self._request("GET", path)
        _apply_checkout_data(payment, res["data"])
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    async def expire_checkout(
        self, db: AsyncSession, payment: FiatPayment
    ) -> FiatPayment:
        """Manually expire a pending FossaPay checkout wallet."""
        if payment.flow != FiatPaymentFlow.CHECKOUT.value or not payment.fossapay_id:
            raise ValueError("Checkout has no FossaPay ID to expire")
        res = await self._request(
            "POST", f"/api/v1/checkouts/{payment.fossapay_id}/expire"
        )
        _apply_checkout_data(payment, res["data"])
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    async def create_payout(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        amount_ngn: int | Decimal | str,
        reference: str,
        bank_code: str,
        bank_name: str,
        account_name: str,
        account_number: str,
        payment_intent_id: UUID | None = None,
        remarks: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> FiatPayment:
        """Send NGN from the business master wallet to a bank or FossaPay wallet."""
        amount = _validate_ngn_integer_amount(amount_ngn)
        _validate_reference(reference)

        payment, already_created = await self._get_or_create_payment(
            db,
            flow=FiatPaymentFlow.PAYOUT,
            reference=reference,
            idempotency_key=idempotency_key,
            defaults={
                "user_id": user_id,
                "payment_intent_id": payment_intent_id,
                "amount": str(amount),
                "bank_code": bank_code,
                "bank_name": bank_name,
                "account_name": account_name,
                "account_number": account_number,
                "metadata_json": json.dumps(metadata) if metadata is not None else None,
                "description": remarks,
                "status": FiatPaymentStatus.PROCESSING.value,
            },
        )
        if already_created:
            return payment

        body: dict[str, Any] = {
            "amount": amount,
            "currency": "NGN",
            "reference": reference,
            "destinationBankCode": bank_code,
            "destinationBankName": bank_name,
            "destinationAccountName": account_name,
            "destinationAccountNumber": account_number,
        }
        if remarks is not None:
            body["remarks"] = remarks
        if metadata is not None:
            body["metadata"] = metadata

        try:
            res = await self._request(
                "POST",
                "/api/v1/payouts",
                json_body=body,
                idempotency_key=payment.idempotency_key,
            )
        except FossaPayError as exc:
            if 400 <= exc.status_code < 500:
                await self._mark_client_failure(db, payment, exc.message)
            raise

        _apply_payout_data(payment, res["data"])
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    async def reconcile_payout(
        self, db: AsyncSession, payment: FiatPayment
    ) -> FiatPayment:
        """Fetch the latest master-wallet payout status from FossaPay."""
        if payment.flow != FiatPaymentFlow.PAYOUT.value:
            raise ValueError("Payment is not a payout record")
        path = (
            f"/api/v1/payouts/{payment.fossapay_id}"
            if payment.fossapay_id
            else f"/api/v1/payouts/reference/{payment.reference}"
        )
        res = await self._request("GET", path)
        _apply_payout_data(payment, res["data"])
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    async def process_webhook(
        self, db: AsyncSession, payload: Mapping[str, Any]
    ) -> tuple[bool, Optional[FiatPayment]]:
        """Deduplicate by eventId and apply checkout/payout webhook updates."""
        event_id = payload.get("eventId")
        event_type = payload.get("eventType")
        data = payload.get("data")
        if not event_id or not event_type or not isinstance(data, Mapping):
            raise ValueError("Invalid FossaPay webhook envelope")

        reference = data.get("reference")
        inbox_event = FossaPayWebhookEvent(
            event_id=str(event_id),
            event_type=str(event_type),
            reference=str(reference) if reference else None,
        )
        try:
            async with db.begin_nested():
                db.add(inbox_event)
                await db.flush()
        except IntegrityError:
            return False, None

        payment: Optional[FiatPayment] = None
        if event_type in CHECKOUT_EVENTS:
            payment = await self._find_payment_for_webhook(
                db,
                fossapay_id=data.get("checkoutId"),
                reference=reference,
            )
            if payment is not None:
                _apply_checkout_data(payment, data)
                payment.last_event_id = str(event_id)
                db.add(payment)
        elif event_type in PAYOUT_EVENTS:
            payment = await self._find_payment_for_webhook(
                db,
                fossapay_id=data.get("payoutId"),
                reference=reference,
            )
            if payment is not None:
                _apply_payout_data(payment, data)
                payment.last_event_id = str(event_id)
                db.add(payment)

        await db.commit()
        if payment is not None:
            await db.refresh(payment)
        return True, payment
