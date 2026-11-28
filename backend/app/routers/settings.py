from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import SettlementTarget
from app.models.user import User
from app.routers.dependencies import get_current_user
from core.session import get_session

router = APIRouter(prefix="/settings", tags=["settings"])


class SettlementSettingsResponse(BaseModel):
    default_target: Literal["crypto", "fiat"]
    is_explicit: bool


class SettlementSettingsUpdate(BaseModel):
    default_target: Literal["crypto", "fiat"]


def effective_settlement_target(user: User) -> str:
    if user.default_settlement_target in {
        SettlementTarget.CRYPTO.value,
        SettlementTarget.FIAT.value,
    }:
        return user.default_settlement_target
    return SettlementTarget.FIAT.value if user.address.startswith("whatsapp:") else SettlementTarget.CRYPTO.value


@router.get("/settlement", response_model=SettlementSettingsResponse)
async def get_settlement_settings(current_user: User = Depends(get_current_user)):
    return SettlementSettingsResponse(
        default_target=effective_settlement_target(current_user),
        is_explicit=current_user.default_settlement_target is not None,
    )


@router.patch("/settlement", response_model=SettlementSettingsResponse)
async def update_settlement_settings(
    payload: SettlementSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if payload.default_target not in {SettlementTarget.CRYPTO.value, SettlementTarget.FIAT.value}:
        raise HTTPException(status_code=422, detail="Unsupported settlement target")
    current_user.default_settlement_target = payload.default_target
    await db.commit()
    return SettlementSettingsResponse(default_target=payload.default_target, is_explicit=True)
