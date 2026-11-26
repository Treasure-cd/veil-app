from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import PaymentIntent
from app.services.rates import get_rates
from core.config import settings


async def create_payment_intent(
    *,
    db: AsyncSession,
    user_id: UUID,
    recipient_address: str,
    amount_ngn: Decimal,
    merchant_ref: str,
    token: Literal["USDC", "SOL"] = "USDC",
    memo: str | None = None,
    source: str = "web",
    receive_mode: Literal["private", "public"] = "private",
    settlement_target: Literal["crypto", "fiat"] = "crypto",
    bank_account_id: UUID | None = None,
) -> PaymentIntent:
    """Create a locked NGN payment request for API routes and integrations."""
    rates = await get_rates()
    rate = rates["usdc" if token == "USDC" else "sol"]
    decimals = 6 if token == "USDC" else 9
    atomic = int(
        (amount_ngn / rate * (Decimal(10) ** decimals)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    if atomic < 1:
        raise HTTPException(
            status_code=400,
            detail="amount_ngn is below the smallest supported token amount",
        )

    now = datetime.now(timezone.utc)
    intent = PaymentIntent(
        user_id=user_id,
        merchant_ref=merchant_ref,
        mint=settings.USDC_MINT if token == "USDC" else settings.SOL_MINT,
        amount_atomic=str(atomic),
        amount_ngn=str(amount_ngn),
        rate_ngn_per_token=str(rate),
        expires_at=now + timedelta(minutes=30),
        recipient_address=recipient_address,
        receive_mode=receive_mode,
        settlement_target=settlement_target,
        bank_account_id=bank_account_id,
        memo=memo,
        status="created",
        source=source,
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return intent
