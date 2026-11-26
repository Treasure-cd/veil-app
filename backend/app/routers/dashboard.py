from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import Numeric, case, cast, func, literal, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import PaymentIntent
from app.models.user import User
from app.routers.dependencies import get_current_user
from core.config import settings
from core.session import get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
PAID_STATUSES = ("funded", "claimed")
CHANNELS = ("whatsapp", "qr", "nfc", "web")


def _ngn_expression():
    """Compute a payment's NGN value from its locked rate, never a current quote."""
    atomic = cast(PaymentIntent.amount_atomic, Numeric)
    decimals = case((PaymentIntent.mint == settings.USDC_MINT, 6), else_=9)
    token_amount = atomic / func.power(cast(literal(10), Numeric), decimals)
    locked_value = token_amount * cast(PaymentIntent.rate_ngn_per_token, Numeric)
    # Older rows can lack a rate; amount_ngn was also persisted with newer intents.
    return case(
        (PaymentIntent.rate_ngn_per_token.is_not(None), locked_value),
        else_=func.coalesce(cast(PaymentIntent.amount_ngn, Numeric), cast(literal(0), Numeric)),
    )


def _channel_expression():
    return case(
        (PaymentIntent.source.in_(CHANNELS), PaymentIntent.source),
        else_=literal("web"),
    )


def _number(value) -> Decimal:
    return Decimal(str(value or 0))


def _fmt(value) -> str:
    return format(_number(value).normalize(), "f")


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _token_symbol(mint: str) -> str:
    if mint == settings.USDC_MINT:
        return "USDC"
    if mint == settings.SOL_MINT:
        return "SOL"
    return "unknown"


def _token_amount(atomic: str, symbol: str) -> str:
    decimals = 6 if symbol == "USDC" else 9
    try:
        return _fmt(Decimal(atomic) / (Decimal(10) ** decimals))
    except (TypeError, ValueError):
        return "0"


@router.get("")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    uid = current_user.id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    daily_start = datetime.combine(today - timedelta(days=29), time.min)
    window_start = now - timedelta(days=30)
    previous_start = window_start - timedelta(days=30)
    ngn = _ngn_expression()
    paid = PaymentIntent.status.in_(PAID_STATUSES)

    aggregate = (await db.execute(
        select(
            func.coalesce(func.sum(case((paid & (PaymentIntent.created_at >= window_start) & (PaymentIntent.created_at < now), ngn), else_=0)), 0),
            func.coalesce(func.sum(case((paid & (PaymentIntent.created_at >= previous_start) & (PaymentIntent.created_at < window_start), ngn), else_=0)), 0),
            func.count(case((paid & (PaymentIntent.created_at >= window_start) & (PaymentIntent.created_at < now), 1))),
            func.avg(case((paid & (PaymentIntent.created_at >= window_start) & (PaymentIntent.created_at < now), ngn), else_=None)),
        ).where(PaymentIntent.user_id == uid)
    )).one()
    volume_30d, volume_prev_30d, transactions_30d, avg_payment = aggregate

    awaiting = (await db.execute(
        select(
            func.count(PaymentIntent.id),
            func.coalesce(func.sum(ngn), 0),
        ).where(
            PaymentIntent.user_id == uid,
            PaymentIntent.status == "funded",
            PaymentIntent.receive_mode == "private",
        )
    )).one()

    channel = _channel_expression().label("channel")
    by_channel_rows = (await db.execute(
        select(
            channel,
            func.coalesce(func.sum(ngn), 0).label("total"),
            func.count(PaymentIntent.id).label("count"),
        ).where(
            PaymentIntent.user_id == uid,
            paid,
        ).group_by(text("channel"))
    )).all()
    by_channel = {key: {"total_ngn": "0", "count": 0} for key in CHANNELS}
    for row in by_channel_rows:
        by_channel[row.channel] = {"total_ngn": _fmt(row.total), "count": row.count}

    by_privacy_rows = (await db.execute(
        select(
            PaymentIntent.receive_mode,
            func.coalesce(func.sum(ngn), 0).label("total"),
            func.count(PaymentIntent.id).label("count"),
        ).where(
            PaymentIntent.user_id == uid,
            paid,
        ).group_by(PaymentIntent.receive_mode)
    )).all()
    by_privacy = {key: {"total_ngn": "0", "count": 0} for key in ("public", "private")}
    for row in by_privacy_rows:
        if row.receive_mode in by_privacy:
            by_privacy[row.receive_mode] = {"total_ngn": _fmt(row.total), "count": row.count}

    day_bucket = func.date_trunc(literal_column("'day'"), PaymentIntent.created_at)

    daily_rows = (await db.execute(
        select(
            day_bucket.label("day"),
            func.coalesce(func.sum(ngn), 0).label("total"),
        ).where(
            PaymentIntent.user_id == uid,
            paid,
            PaymentIntent.created_at >= daily_start,
            PaymentIntent.created_at < now,
        ).group_by(day_bucket)
    )).all()


    daily_by_date = {
        (row.day.date() if isinstance(row.day, datetime) else row.day): _fmt(row.total)
        for row in daily_rows
    }
    daily_volume = [
        {"date": (daily_start.date() + timedelta(days=offset)).isoformat(),
         "amount_ngn": daily_by_date.get(daily_start.date() + timedelta(days=offset), "0")}
        for offset in range(30)
    ]
    vault_total_result = await db.execute(text("""
            SELECT COALESCE(SUM(
                COALESCE(
                    COALESCE((
                        SELECT SUM(COALESCE((recipient.value->>'amountAtomic')::numeric, 0))
                        FROM jsonb_array_elements(CAST(recipients_json AS jsonb)) AS recipient(value)
                    ), 0) * rate_ngn_per_token::numeric
                        / POWER(10::numeric, CASE WHEN token = 'USDC' THEN 6 ELSE 9 END),
                    COALESCE((
                        SELECT SUM(COALESCE((recipient.value->>'amountNgn')::numeric, 0))
                        FROM jsonb_array_elements(CAST(recipients_json AS jsonb)) AS recipient(value)
                    ), 0)
                )
            ), 0)
            FROM payroll_groups
            WHERE user_id = :user_id AND status IN ('locked', 'scheduled')
        """), {"user_id": uid})
    vault_locked_ngn = vault_total_result.scalar_one()

    recent_rows = (await db.execute(
        select(PaymentIntent, ngn.label("amount_ngn"))
        .where(PaymentIntent.user_id == uid)
        .order_by(PaymentIntent.created_at.desc())
        .limit(10)
    )).all()
    recent_activity = []
    for intent, amount_ngn in recent_rows:
        token = _token_symbol(intent.mint)
        recent_activity.append({
            "id": str(intent.id),
            "title": intent.memo or intent.merchant_ref,
            "channel": intent.source if intent.source in CHANNELS[:-1] else "web",
            "status": intent.status,
            "amount_ngn": _fmt(amount_ngn),
            "token": token,
            "token_amount": _token_amount(intent.amount_atomic, token),
            "created_at": _utc_iso(intent.created_at),
        })

    volume = _number(volume_30d)
    previous_volume = _number(volume_prev_30d)
    change_percent = ((volume - previous_volume) / previous_volume * 100) if previous_volume else None

    return {
        "volume_30d_ngn": _fmt(volume),
        "volume_prev_30d_ngn": _fmt(previous_volume),
        "volume_change_percent": _fmt(change_percent) if change_percent is not None else None,
        "transactions_30d": transactions_30d,
        "awaiting_claim_count": awaiting[0],
        "awaiting_claim_ngn": _fmt(awaiting[1]),
        "vault_locked_ngn": _fmt(vault_locked_ngn),
        "avg_payment_ngn": _fmt(avg_payment),
        "daily_volume": daily_volume,
        "by_channel": by_channel,
        "by_privacy": by_privacy,
        "recent_activity": recent_activity,
    }
