import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.payment import (
    MerchantBankAccount,
    PajOfframpOrder,
    PajOrderStatus,
    utc_now,
)
from core.config import settings

PAJ_SOLANA_TOKENS: dict[str, dict[str, Any]] = {
    "USDC": {
        "symbol": "USDC",
        "name": "USD Coin",
        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "decimals": 6,
    },
    "SOL": {
        "symbol": "SOL",
        "name": "Solana",
        "mint": "So11111111111111111111111111111111111111112",
        "decimals": 9,
    },
    "USDT": {
        "symbol": "USDT",
        "name": "Tether USD",
        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "decimals": 6,
    },
    "USDG": {
        "symbol": "USDG",
        "name": "Global Dollar",
        "mint": "2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH",
        "decimals": 6,
    },
}


class PajCashError(Exception):
    """Raised when a Paj Cash API request fails or returns an error payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.payload = payload


def verify_paj_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str | None = None,
    *,
    max_age_seconds: int = 300,
) -> bool:
    """Verify Paj Cash HMAC-SHA256 signature over '{timestamp}.{raw_body}'."""
    webhook_secret = secret if secret is not None else settings.PAJCASH_WEBHOOK_SECRET
    if not webhook_secret:
        return False

    timestamp = ""
    signature = ""
    for key, value in headers.items():
        lowered = key.lower()
        if lowered == "x-paj-timestamp":
            timestamp = str(value or "")
        elif lowered == "x-paj-signature":
            signature = str(value or "").removeprefix("v1=")

    if not timestamp or not signature:
        return False
    try:
        ts_int = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts_int) > max_age_seconds:
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _apply_offramp_data(order: PajOfframpOrder, data: Mapping[str, Any]) -> None:
    if data.get("id"):
        order.paj_order_id = str(data["id"])
    if data.get("address"):
        order.deposit_address = str(data["address"])
    if data.get("amount") is not None:
        order.token_amount = str(data["amount"])
    if data.get("fiatAmount") is not None:
        order.fiat_amount = str(data["fiatAmount"])
    if data.get("rate") is not None:
        order.rate = str(data["rate"])
    if data.get("fee") is not None:
        order.fee_usdc = str(data["fee"])
    if data.get("signature"):
        order.tx_signature = str(data["signature"])
    if data.get("accountName"):
        order.account_name = str(data["accountName"])
    if data.get("bank"):
        order.bank_name = str(data["bank"])
    if data.get("status"):
        next_status = str(data["status"])
        if order.status != PajOrderStatus.COMPLETED.value or next_status == PajOrderStatus.COMPLETED.value:
            order.status = next_status
    order.updated_at = utc_now()


class PajCashService:
    """Async client and persistence layer for Paj Cash bank accounts and offramps."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else (settings.PAJCASH_APIKEY or "")
        self.base_url = (base_url or settings.PAJCASH_BASE_URL).rstrip("/")
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retry_on_network_error: bool = False,
    ) -> Any:
        if not self.api_key:
            raise PajCashError("PAJCASH_APIKEY is not configured", status_code=503)

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        attempts = 2 if retry_on_network_error else 1

        async def _execute(client: aiohttp.ClientSession) -> Any:
            last_exc: Exception | None = None
            for attempt in range(attempts):
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
                                if isinstance(parsed, dict)
                                else None
                            ) or (
                                parsed.get("error")
                                if isinstance(parsed, dict)
                                else None
                            ) or f"Paj Cash request failed with status {response.status}"
                            raise PajCashError(
                                str(msg),
                                status_code=response.status,
                                payload=parsed if isinstance(parsed, dict) else None,
                            )
                        return parsed
                except aiohttp.ClientError as exc:
                    last_exc = exc
                    if attempt + 1 < attempts:
                        continue
            raise PajCashError(f"Paj Cash network error: {last_exc}", status_code=503)

        if self._session is not None:
            return await _execute(self._session)

        async with aiohttp.ClientSession(timeout=self._timeout) as client:
            return await _execute(client)

    async def get_rates(self, currency: str = "NGN") -> dict[str, Any]:
        return await self._request(
            "GET",
            "/pub/v2/rate",
            params={"currency": currency},
            retry_on_network_error=True,
        )

    async def get_banks(
        self, *, name: str | None = None, code: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if code:
            params["code"] = code
        res = await self._request(
            "GET",
            "/pub/v2/bank",
            params=params or None,
            retry_on_network_error=True,
        )
        return list(res or [])

    async def get_token(self, mint: str, chain: str = "SOLANA") -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/pub/v2/tokens/{mint}",
            params={"chain": chain},
            retry_on_network_error=True,
        )

    async def resolve_solana_token(self, token_or_mint: str) -> dict[str, Any]:
        upper = token_or_mint.strip().upper()
        if upper in PAJ_SOLANA_TOKENS:
            return PAJ_SOLANA_TOKENS[upper]
        info = await self.get_token(token_or_mint.strip(), chain="SOLANA")
        raw_decimals = info.get("decimals")
        return {
            "symbol": info.get("symbol") or "TOKEN",
            "name": info.get("name") or "Solana Token",
            "mint": info.get("address") or token_or_mint.strip(),
            "decimals": int(raw_decimals) if raw_decimals is not None else 6,
        }

    async def register_bank_account(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        bank_code: str,
        account_number: str,
        make_default: bool = True,
    ) -> MerchantBankAccount:
        """Register a Nigerian bank account with Paj Cash and persist its Solana deposit address."""
        res = await self._request(
            "POST",
            "/pub/v2/bank-account",
            json_body={"bankCode": bank_code, "accountNumber": account_number},
            retry_on_network_error=True,
        )

        if make_default:
            existing_rows = (
                await db.execute(
                    select(MerchantBankAccount).where(
                        MerchantBankAccount.user_id == user_id,
                        MerchantBankAccount.is_default == True,  # noqa: E712
                    )
                )
            ).scalars().all()
            for row in existing_rows:
                row.is_default = False
                row.updated_at = utc_now()
                db.add(row)

        existing = (
            await db.execute(
                select(MerchantBankAccount).where(
                    MerchantBankAccount.user_id == user_id,
                    MerchantBankAccount.bank_code == bank_code,
                    MerchantBankAccount.account_number == account_number,
                )
            )
        ).scalars().first()

        if existing:
            existing.paj_account_id = str(res["id"])
            existing.bank_name = str(res["bank"])
            existing.account_name = str(res["accountName"])
            existing.solana_address = str(res["address"])
            existing.evm_address = res.get("evmAddress")
            if make_default:
                existing.is_default = True
            existing.updated_at = utc_now()
            account = existing
        else:
            account = MerchantBankAccount(
                user_id=user_id,
                paj_account_id=str(res["id"]),
                bank_code=bank_code,
                bank_name=str(res["bank"]),
                account_number=str(res.get("accountNumber") or account_number),
                account_name=str(res["accountName"]),
                solana_address=str(res["address"]),
                evm_address=res.get("evmAddress"),
                is_default=make_default,
            )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def create_offramp_order(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        bank_code: str,
        account_number: str,
        mint: str,
        token_symbol: str,
        token_decimals: int = 6,
        fiat_amount: Decimal | int | str | None = None,
        token_amount: Decimal | int | str | None = None,
        payment_intent_id: UUID | None = None,
        bank_account_id: UUID | None = None,
        bank_name: str | None = None,
        account_name: str | None = None,
        narration: str | None = None,
        webhook_url: str | None = None,
    ) -> PajOfframpOrder:
        """Create a Paj Cash offramp order for a specific Solana token and NGN/token amount."""
        if (fiat_amount is None) == (token_amount is None):
            raise ValueError("Provide exactly one of fiat_amount or token_amount")

        body: dict[str, Any] = {
            "bankCode": bank_code,
            "accountNumber": account_number,
            "currency": "NGN",
            "chain": "SOLANA",
            "mint": mint,
        }
        if fiat_amount is not None:
            dec = Decimal(str(fiat_amount))
            if not dec.is_finite() or dec <= 0:
                raise ValueError("fiat_amount must be positive")
            body["fiatAmount"] = float(dec) if dec != dec.to_integral_value() else int(dec)
        else:
            dec = Decimal(str(token_amount))
            if not dec.is_finite() or dec <= 0:
                raise ValueError("token_amount must be positive")
            body["amount"] = float(dec)

        if narration:
            body["narration"] = narration[:100]
        if webhook_url:
            body["webhookURL"] = webhook_url

        res = await self._request("POST", "/pub/v2/offramp", json_body=body)
        now_utc = datetime.now(timezone.utc)
        order = PajOfframpOrder(
            user_id=user_id,
            payment_intent_id=payment_intent_id,
            bank_account_id=bank_account_id,
            paj_order_id=str(res["id"]),
            chain=str(res.get("chain") or "SOLANA"),
            mint=str(res.get("mint") or mint),
            token_symbol=token_symbol,
            token_decimals=token_decimals,
            deposit_address=str(res["address"]),
            token_amount=str(res["amount"]) if res.get("amount") is not None else None,
            fiat_amount=str(res["fiatAmount"]) if res.get("fiatAmount") is not None else None,
            currency=str(res.get("currency") or "NGN"),
            rate=str(res["rate"]) if res.get("rate") is not None else None,
            fee_usdc=str(res["fee"]) if res.get("fee") is not None else None,
            bank_code=bank_code,
            bank_name=res.get("bank") or bank_name,
            account_number=str(res.get("accountNumber") or account_number),
            account_name=res.get("accountName") or account_name,
            status=str(res.get("status") or PajOrderStatus.INIT.value),
            tx_signature=res.get("signature"),
            narration=narration[:100] if narration else None,
            # Paj lent addresses can be reassigned if unfunded for 2 hours.
            expires_at=now_utc + timedelta(hours=2),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def reconcile_offramp_order(
        self, db: AsyncSession, order: PajOfframpOrder
    ) -> PajOfframpOrder:
        """Fetch latest offramp order state from Paj Cash outside webhooks."""
        if not order.paj_order_id:
            raise ValueError("Offramp order has no Paj order ID")
        try:
            res = await self._request(
                "GET",
                f"/pub/v2/transaction/{order.paj_order_id}",
                retry_on_network_error=True,
            )
        except PajCashError as exc:
            if exc.status_code == 404 and order.status == PajOrderStatus.INIT.value:
                order.status = PajOrderStatus.ERROR.value
                order.failure_reason = "Offramp order expired or not found on Paj Cash"
                order.updated_at = utc_now()
                db.add(order)
                await db.commit()
                await db.refresh(order)
                return order
            raise

        _apply_offramp_data(order, res)
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def process_ramp_webhook(
        self, db: AsyncSession, payload: Mapping[str, Any]
    ) -> Optional[PajOfframpOrder]:
        """Update a PajOfframpOrder from a verified Paj Cash ramp webhook."""
        paj_id = payload.get("id")
        if not paj_id:
            return None
        order = (
            await db.execute(
                select(PajOfframpOrder).where(
                    PajOfframpOrder.paj_order_id == str(paj_id)
                )
            )
        ).scalars().first()
        if order is None:
            return None
        _apply_offramp_data(order, payload)
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order
