from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import Numeric, case, cast, func, literal, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import (
    FiatPayment,
    FiatPaymentFlow,
    PajOfframpOrder,
    PajOrderStatus,
    PaymentIntent,
    SettlementTarget,
)
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
    decimals = case((PaymentIntent.mint.in_(settings.known_usdc_mints), 6), else_=9)
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
    if mint in settings.known_usdc_mints:
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


def _resolve_paid_via(
    intent: PaymentIntent,
    paj_order: PajOfframpOrder | None,
    fiat_checkout: FiatPayment | None,
) -> str | None:
    if intent.paid_via is not None:
        return intent.paid_via
    if paj_order and paj_order.status in (PajOrderStatus.PROCESSING.value, PajOrderStatus.COMPLETED.value):
        return "paj"
    if fiat_checkout and fiat_checkout.status == "completed":
        return "fossapay"
    if intent.fund_signature:
        return "paj" if intent.settlement_target == SettlementTarget.FIAT.value else "crypto"
    return None


def _resolve_settlement_status(
    intent: PaymentIntent,
    paj_order: PajOfframpOrder | None,
    fiat_payout: FiatPayment | None,
) -> str:
    if intent.settlement_target != SettlementTarget.FIAT.value:
        if intent.status == "failed":
            return "expired" if intent.failure_reason == "expired" else "failed"
        if intent.receive_mode == "private":
            if intent.status == "claimed":
                return "settled"
            if intent.status == "funded":
                return "awaiting_claim"
            return "pending"
        return "settled" if intent.status == "funded" else "pending"

    if paj_order is not None:
        if paj_order.status == PajOrderStatus.COMPLETED.value:
            return "settled"
        if paj_order.status == PajOrderStatus.PROCESSING.value:
            return "settling"
        if paj_order.status == PajOrderStatus.ERROR.value:
            return "failed"
        return "settling" if intent.status == "funded" else "pending"
    if fiat_payout is not None:
        if fiat_payout.status == "completed":
            return "settled"
        if fiat_payout.status in ("pending", "processing"):
            return "settling"
        return "failed"
    if intent.status in ("funded", "claimed"):
        return "settling"
    if intent.status == "failed":
        return "expired" if intent.failure_reason == "expired" else "failed"
    return "pending"


async def _load_recent_activity(db: AsyncSession, uid, ngn) -> list[dict]:
    recent_rows = (await db.execute(
        select(PaymentIntent, ngn.label("amount_ngn"))
        .where(PaymentIntent.user_id == uid)
        .order_by(PaymentIntent.created_at.desc())
        .limit(10)
    )).all()
    recent_ids = [intent.id for intent, _ in recent_rows]

    paj_priority = {
        PajOrderStatus.COMPLETED.value: 0,
        PajOrderStatus.PROCESSING.value: 1,
        PajOrderStatus.INIT.value: 2,
        PajOrderStatus.ERROR.value: 3,
    }
    paj_by_intent: dict = {}
    checkout_by_intent: dict = {}
    payout_by_intent: dict = {}

    if recent_ids:
        paj_rows = (await db.execute(
            select(PajOfframpOrder)
            .where(PajOfframpOrder.payment_intent_id.in_(recent_ids))
            .order_by(PajOfframpOrder.updated_at.desc(), PajOfframpOrder.created_at.desc())
        )).scalars().all()
        for order in paj_rows:
            existing = paj_by_intent.get(order.payment_intent_id)
            if existing is None or paj_priority.get(order.status, 99) < paj_priority.get(existing.status, 99):
                paj_by_intent[order.payment_intent_id] = order

        fiat_rows = (await db.execute(
            select(FiatPayment)
            .where(FiatPayment.payment_intent_id.in_(recent_ids))
            .order_by(FiatPayment.created_at.desc())
        )).scalars().all()
        for row in fiat_rows:
            if row.flow == FiatPaymentFlow.CHECKOUT.value and row.payment_intent_id not in checkout_by_intent:
                checkout_by_intent[row.payment_intent_id] = row
            elif row.flow == FiatPaymentFlow.PAYOUT.value and row.payment_intent_id not in payout_by_intent:
                payout_by_intent[row.payment_intent_id] = row

    recent_activity = []
    for intent, amount_ngn in recent_rows:
        paj_order = paj_by_intent.get(intent.id)
        fiat_checkout = checkout_by_intent.get(intent.id)
        fiat_payout = payout_by_intent.get(intent.id)
        paid_via = _resolve_paid_via(intent, paj_order, fiat_checkout)
        settlement_status = _resolve_settlement_status(intent, paj_order, fiat_payout)

        if paj_order and paj_order.token_amount:
            token = paj_order.token_symbol
            token_amount = paj_order.token_amount
        else:
            token = _token_symbol(intent.mint)
            token_amount = _token_amount(intent.amount_atomic, token)

        recent_activity.append({
            "id": str(intent.id),
            "title": intent.memo or intent.merchant_ref,
            "channel": intent.source if intent.source in CHANNELS[:-1] else "web",
            "status": intent.status,
            "settlement_target": intent.settlement_target,
            "paid_via": paid_via,
            "settlement_status": settlement_status,
            "paj_status": paj_order.status if paj_order else None,
            "amount_ngn": _fmt(amount_ngn),
            "token": token,
            "token_amount": token_amount,
            "created_at": _utc_iso(intent.created_at),
        })

    return recent_activity


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

    recent_activity = await _load_recent_activity(db, uid, ngn)

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
