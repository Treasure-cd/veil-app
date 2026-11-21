from datetime import datetime, timezone
from decimal import Decimal
import time

import httpx
from fastapi import HTTPException

from core.config import settings

_cache: dict | None = None
_cached_at = 0.0


async def get_rates() -> dict:
    """Return NGN per token, cached in this process for one minute."""
    global _cache, _cached_at
    if _cache is not None and time.monotonic() - _cached_at < 60:
        return _cache
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "solana,usd-coin", "vs_currencies": "ngn"},
            )
            response.raise_for_status()
            data = response.json()
            sol = Decimal(str(data["solana"]["ngn"]))
            usdc = Decimal(str(data["usd-coin"]["ngn"]))
            if sol <= 0 or usdc <= 0:
                raise ValueError("CoinGecko returned a non-positive rate")
        rates = {"sol": sol, "usdc": usdc}
    except Exception:
        sol, usdc = settings.RATE_NGN_PER_SOL, settings.RATE_NGN_PER_USDC
        if not sol or not usdc:
            raise HTTPException(status_code=503, detail="NGN rates are unavailable")
        rates = {"sol": Decimal(str(sol)), "usdc": Decimal(str(usdc))}
    _cache = {**rates, "asOf": datetime.now(timezone.utc)}
    _cached_at = time.monotonic()
    return _cache
