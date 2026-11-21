from fastapi import APIRouter

from app.services.rates import get_rates

router = APIRouter(prefix="/rates", tags=["rates"])


@router.get("")
async def rates():
    result = await get_rates()
    return {
        "sol": str(result["sol"]),
        "usdc": str(result["usdc"]),
        "asOf": result["asOf"].isoformat().replace("+00:00", "Z"),
    }
