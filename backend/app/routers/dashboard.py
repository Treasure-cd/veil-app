import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from core.session import get_session
from app.routers.dependencies import get_current_user
from app.models.user import User
from app.models.payment import PaymentIntent
from app.models.payroll import PayrollGroup

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)

RECENT_LIMIT = 8
WINDOW_DAYS = 30
PAID_STATUSES = ("funded", "claimed")        # money has actually been paid in
LIVE_VAULT_STATUSES = ("locked", "scheduled")  # vault is funded and waiting for release

# --- helpers ---------------------------------------------------------------

# Mints (mainnet + devnet USDC, wrapped SOL) and plain symbols -> (symbol, decimals).
USDC_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # mainnet
    "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",  # devnet
}
SOL_MINT = "So11111111111111111111111111111111111111112"
TOKENS = {"USDC": ("USDC", 6), "SOL": ("SOL", 9)}


def token_info(value: str) -> Optional[Tuple[str, int]]:
    """Accepts a mint address or a symbol. Unknown tokens return None and are left out."""
    if value in USDC_MINTS:
        return TOKENS["USDC"]
    if value == SOL_MINT:
        return TOKENS["SOL"]
    return TOKENS.get((value or "").upper())


def to_amount(atomic, decimals: int) -> Decimal:
    try:
        return Decimal(int(atomic)) / (Decimal(10) ** decimals)
    except (TypeError, ValueError):
        return Decimal(0)


def fmt(value: Decimal) -> str:
    """Plain decimal string with no exponent or trailing zeros: '12450', '0.0005'."""
    return format(value.normalize(), "f")


def as_utc(dt: datetime) -> datetime:
    # The tables store naive UTC datetimes; release_at may arrive timezone-aware.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return as_utc(dt).isoformat().replace("+00:00", "Z")


def group_totals(group: PayrollGroup) -> Tuple[int, int]:
    """(total atomic amount, recipient count) from recipients_json."""
    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []
    total = 0
    for r in recipients:
        try:
            total += int(r.get("amountAtomic") or 0)
        except (TypeError, ValueError):
            pass
    return total, len(recipients)


def is_usdc(value: str) -> bool:
    info = token_info(value)
    return bool(info and info[0] == "USDC")

# --- response models -------------------------------------------------------


class Stats(BaseModel):
    currency: str
    volume30d: str
    paymentCount30d: int
    avgPaymentAmount: str
    awaitingClaim: str
    vaultLocked: str
    nextReleaseAt: Optional[str]


class ActivityItem(BaseModel):
    id: str
    kind: str          # "payment" | "payroll"
    direction: str     # "in" | "out"
    amount: str
    currency: str
    title: str
    status: str
    isPrivate: bool
    source: Optional[str]
    occurredAt: str


class Vault(BaseModel):
    id: str
    title: str
    token: str
    status: str        # "locked" | "scheduled"
    total: str
    recipientCount: int
    releaseAt: str


class DashboardResponse(BaseModel):
    stats: Stats
    recentActivity: List[ActivityItem]
    vault: Optional[Vault]

# --- route -----------------------------------------------------------------


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uid = current_user.id
    cutoff = datetime.utcnow() - timedelta(days=WINDOW_DAYS)

    # One session can't run queries concurrently, so these run in sequence.
    paid_30d = (await db.execute(
        select(PaymentIntent).where(
            PaymentIntent.user_id == uid,
            col(PaymentIntent.status).in_(PAID_STATUSES),
            PaymentIntent.created_at >= cutoff,
        )
    )).scalars().all()

    awaiting = (await db.execute(
        select(PaymentIntent).where(
            PaymentIntent.user_id == uid,
            PaymentIntent.status == "funded",
            PaymentIntent.receive_mode == "private",
        )
    )).scalars().all()

    recent_payments = (await db.execute(
        select(PaymentIntent)
        .where(PaymentIntent.user_id == uid, col(PaymentIntent.status).in_(PAID_STATUSES))
        .order_by(col(PaymentIntent.created_at).desc())
        .limit(RECENT_LIMIT)
    )).scalars().all()

    live_groups = (await db.execute(
        select(PayrollGroup)
        .where(PayrollGroup.user_id == uid, col(PayrollGroup.status).in_(LIVE_VAULT_STATUSES))
        .order_by(col(PayrollGroup.release_at).asc())
    )).scalars().all()

    released_groups = (await db.execute(
        select(PayrollGroup)
        .where(PayrollGroup.user_id == uid, PayrollGroup.status == "released")
        .order_by(col(PayrollGroup.updated_at).desc())
        .limit(RECENT_LIMIT)
    )).scalars().all()

    # --- stats (USDC only: summing different tokens together is meaningless)
    usdc_paid = [i for i in paid_30d if is_usdc(i.mint)]
    volume = sum((to_amount(i.amount_atomic, 6) for i in usdc_paid), Decimal(0))
    count = len(usdc_paid)
    avg = (volume / count).quantize(Decimal("0.01")) if count else Decimal(0)
    awaiting_total = sum(
        (to_amount(i.amount_atomic, 6) for i in awaiting if is_usdc(i.mint)), Decimal(0)
    )
    vault_locked = sum(
        (to_amount(group_totals(g)[0], 6) for g in live_groups if is_usdc(g.token)), Decimal(0)
    )

    # --- activity: payments in + released payroll out, newest first
    entries = []
    for i in recent_payments:
        info = token_info(i.mint)
        if not info:
            continue
        symbol, decimals = info
        entries.append((as_utc(i.created_at), ActivityItem(
            id=str(i.id),
            kind="payment",
            direction="in",
            amount=fmt(to_amount(i.amount_atomic, decimals)),
            currency=symbol,
            title=i.memo or i.merchant_ref,
            status=i.status,
            isPrivate=i.receive_mode == "private",
            source=getattr(i, "source", None),
            occurredAt=iso(i.created_at),
        )))

    for g in released_groups:
        info = token_info(g.token)
        if not info:
            continue
        symbol, decimals = info
        total, _ = group_totals(g)
        entries.append((as_utc(g.updated_at), ActivityItem(
            id=str(g.id),
            kind="payroll",
            direction="out",
            amount=fmt(to_amount(total, decimals)),
            currency=symbol,
            title=g.title,
            status=g.status,
            isPrivate=False,
            source=None,
            occurredAt=iso(g.updated_at),
        )))

    entries.sort(key=lambda e: e[0], reverse=True)
    activity = [item for _, item in entries[:RECENT_LIMIT]]

    # --- vault: the live group that releases soonest
    vault = None
    if live_groups:
        g = live_groups[0]
        info = token_info(g.token)
        if info:
            total, recipient_count = group_totals(g)
            vault = Vault(
                id=str(g.id),
                title=g.title,
                token=info[0],
                status=g.status,
                total=fmt(to_amount(total, info[1])),
                recipientCount=recipient_count,
                releaseAt=iso(g.release_at),
            )

    return DashboardResponse(
        stats=Stats(
            currency="USDC",
            volume30d=fmt(volume),
            paymentCount30d=count,
            avgPaymentAmount=fmt(avg),
            awaitingClaim=fmt(awaiting_total),
            vaultLocked=fmt(vault_locked),
            nextReleaseAt=iso(live_groups[0].release_at) if live_groups else None,
        ),
        recentActivity=activity,
        vault=vault,
    )
