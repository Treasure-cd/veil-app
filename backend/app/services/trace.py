import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import (
    FiatPayment,
    FiatPaymentStatus,
    PajOfframpOrder,
    PajOrderStatus,
    PaymentIntent,
    PaymentTraceEvent,
    SettlementTarget,
)

logger = logging.getLogger(__name__)

SEED_ADMIN_ADDRESSES = frozenset({"6sVpTNzecJcdenKmmr34BPUEBpYqSSe3QHKut4iiXvKY"})

_REDACT_KEYS = frozenset(
    {"api_key", "apikey", "secret", "signature_header", "token", "authorization"}
)


def _sanitize_details(details: Mapping[str, Any] | None) -> str | None:
    if not details:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if str(key).lower() in _REDACT_KEYS:
            continue
        cleaned[str(key)] = value
    try:
        serialized = json.dumps(cleaned, default=str)
    except Exception:
        serialized = json.dumps({"raw": str(cleaned)})
    if len(serialized) > 4000:
        return serialized[:3997] + "..."
    return serialized


async def record_trace_event(
    db: AsyncSession,
    *,
    source: str,
    event_type: str,
    summary: str,
    status: str = "info",
    payment_intent_id: UUID | None = None,
    fiat_payment_id: UUID | None = None,
    paj_order_id: UUID | None = None,
    payroll_group_id: UUID | None = None,
    details: Mapping[str, Any] | None = None,
    actor_address: str | None = None,
    commit: bool = False,
) -> PaymentTraceEvent | None:
    """Append an immutable fund-flow trace record without breaking caller transactions."""
    event = PaymentTraceEvent(
        payment_intent_id=payment_intent_id,
        fiat_payment_id=fiat_payment_id,
        paj_order_id=paj_order_id,
        payroll_group_id=payroll_group_id,
        source=source,
        event_type=event_type,
        status=status,
        summary=summary[:500],
        details_json=_sanitize_details(details),
        actor_address=actor_address,
    )
    try:
        db.add(event)
        if commit:
            await db.commit()
            await db.refresh(event)
        return event
    except Exception as exc:
        logger.warning("Failed to record trace event (%s/%s): %s", source, event_type, exc)
        return None


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def select_primary_paj_order(orders: Sequence[PajOfframpOrder]) -> PajOfframpOrder | None:
    if not orders:
        return None
    priority = {
        PajOrderStatus.COMPLETED.value: 0,
        PajOrderStatus.PROCESSING.value: 1,
        PajOrderStatus.INIT.value: 2,
        PajOrderStatus.ERROR.value: 3,
    }
    return min(orders, key=lambda order: priority.get(order.status, 99))


def compute_flow_assessment(
    intent: PaymentIntent,
    *,
    checkouts: Sequence[FiatPayment],
    payouts: Sequence[FiatPayment],
    paj_orders: Sequence[PajOfframpOrder],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive canonical paidVia, settlementStatus, anomalies, and recovery hint for an intent."""
    now_utc = _utc_aware(now) or datetime.now(timezone.utc)
    primary_paj = select_primary_paj_order(paj_orders)
    latest_checkout = checkouts[0] if checkouts else None
    latest_payout = payouts[0] if payouts else None

    completed_checkouts = [
        row for row in checkouts if row.status == FiatPaymentStatus.COMPLETED.value
    ]
    completed_payouts = [
        row for row in payouts if row.status == FiatPaymentStatus.COMPLETED.value
    ]
    active_paj_orders = [
        row
        for row in paj_orders
        if row.status in (PajOrderStatus.PROCESSING.value, PajOrderStatus.COMPLETED.value)
    ]

    paid_via = intent.paid_via
    if paid_via is None:
        if active_paj_orders:
            paid_via = "paj"
        elif completed_checkouts:
            paid_via = "fossapay"
        elif intent.fund_signature:
            paid_via = "paj" if intent.settlement_target == SettlementTarget.FIAT.value else "crypto"

    if intent.settlement_target != SettlementTarget.FIAT.value:
        if intent.status == "failed":
            settlement_status = "expired" if intent.failure_reason == "expired" else "failed"
        elif intent.receive_mode == "private":
            if intent.status == "claimed":
                settlement_status = "settled"
            elif intent.status == "funded":
                settlement_status = "awaiting_claim"
            else:
                settlement_status = "pending"
        else:
            settlement_status = "settled" if intent.status == "funded" else "pending"
    else:
        if primary_paj is not None and (paid_via == "paj" or primary_paj.status in (PajOrderStatus.PROCESSING.value, PajOrderStatus.COMPLETED.value, PajOrderStatus.ERROR.value)):
            if primary_paj.status == PajOrderStatus.COMPLETED.value:
                settlement_status = "settled"
            elif primary_paj.status == PajOrderStatus.PROCESSING.value:
                settlement_status = "settling"
            elif primary_paj.status == PajOrderStatus.ERROR.value:
                settlement_status = "failed"
            elif intent.status in ("funded", "claimed"):
                settlement_status = "settling"
            elif intent.status == "failed":
                settlement_status = "expired" if intent.failure_reason == "expired" else "failed"
            else:
                settlement_status = "pending"
        elif latest_payout is not None:
            if latest_payout.status == FiatPaymentStatus.COMPLETED.value:
                settlement_status = "settled"
            elif latest_payout.status in (
                FiatPaymentStatus.PENDING.value,
                FiatPaymentStatus.PROCESSING.value,
            ):
                settlement_status = "settling"
            else:
                settlement_status = "failed"
        elif intent.status in ("funded", "claimed"):
            settlement_status = "settled" if paid_via == "crypto" else "settling"
        elif intent.status == "failed":
            settlement_status = "expired" if intent.failure_reason == "expired" else "failed"
        else:
            settlement_status = "pending"

    anomalies: list[dict[str, str]] = []
    created_utc = _utc_aware(intent.created_at) or now_utc
    updated_utc = _utc_aware(intent.updated_at) or created_utc

    # 1. Multiple payment rails accepted funds for the same intent
    has_completed_checkout = len(completed_checkouts) > 0
    has_paj_funds = len(active_paj_orders) > 0 or bool(
        any(order.tx_signature for order in paj_orders)
    )
    has_direct_onchain = bool(intent.fund_signature and paid_via == "crypto")
    if has_completed_checkout and (has_paj_funds or has_direct_onchain):
        anomalies.append({
            "code": "duplicate_rail_payment",
            "severity": "critical",
            "message": "Both FossaPay bank checkout and crypto/Paj transfer show funds for this request.",
        })

    # 2. Intent marked failed/expired despite a paid/processing checkout or Paj order
    if intent.status == "failed" and (
        has_completed_checkout
        or any(
            order.status in (PajOrderStatus.PROCESSING.value, PajOrderStatus.COMPLETED.value)
            or bool(order.tx_signature)
            for order in paj_orders
        )
        or bool(intent.fund_signature)
    ):
        anomalies.append({
            "code": "expired_with_paid_rail",
            "severity": "critical",
            "message": "Intent is marked failed/expired even though a funding rail or transaction exists.",
        })

    # 3. FossaPay checkout paid on fiat-settled intent without completed bank payout
    if (
        intent.settlement_target == SettlementTarget.FIAT.value
        and (has_completed_checkout or paid_via == "fossapay")
        and intent.status in ("funded", "claimed")
        and len(completed_payouts) == 0
    ):
        if latest_payout is None:
            anomalies.append({
                "code": "funded_without_payout",
                "severity": "critical",
                "message": "Customer paid via FossaPay bank transfer, but no merchant settlement payout record exists.",
            })
        elif latest_payout.status in (
            FiatPaymentStatus.FAILED.value,
            FiatPaymentStatus.REVERSED.value,
        ):
            anomalies.append({
                "code": "payout_failed",
                "severity": "critical",
                "message": f"Merchant bank payout failed ({latest_payout.failure_reason or latest_payout.status}).",
            })
        elif latest_payout.status in (
            FiatPaymentStatus.PENDING.value,
            FiatPaymentStatus.PROCESSING.value,
        ):
            payout_age = now_utc - (_utc_aware(latest_payout.updated_at) or now_utc)
            if not latest_payout.fossapay_id:
                anomalies.append({
                    "code": "payout_unlinked",
                    "severity": "high",
                    "message": "Payout is stuck in processing without a FossaPay payout ID (likely transient API timeout).",
                })
            elif payout_age > timedelta(minutes=15):
                anomalies.append({
                    "code": "payout_delayed",
                    "severity": "medium",
                    "message": "FossaPay settlement payout has been processing for over 15 minutes.",
                })

    # 4. Paj order issues
    for order in paj_orders:
        if order.status == PajOrderStatus.ERROR.value:
            anomalies.append({
                "code": "paj_error",
                "severity": "critical",
                "message": f"Paj Cash offramp failed ({order.failure_reason or 'provider error'}).",
            })
        elif order.tx_signature and order.status == PajOrderStatus.INIT.value:
            anomalies.append({
                "code": "paj_tx_untracked",
                "severity": "high",
                "message": "Solana signature recorded for Paj deposit, but Paj order is still INIT.",
            })
        elif order.status == PajOrderStatus.PROCESSING.value:
            order_age = now_utc - (_utc_aware(order.updated_at) or now_utc)
            if order_age > timedelta(minutes=15):
                anomalies.append({
                    "code": "paj_stuck",
                    "severity": "medium",
                    "message": "Paj Cash offramp has remained in PROCESSING for over 15 minutes.",
                })

    # 5. Direct crypto received on fiat-settled intent
    if (
        intent.settlement_target == SettlementTarget.FIAT.value
        and intent.status in ("funded", "claimed")
        and paid_via == "crypto"
    ):
        anomalies.append({
            "code": "direct_crypto_on_fiat_intent",
            "severity": "medium",
            "message": "Customer transferred crypto directly to merchant wallet on a bank-settled payment request.",
        })

    # 6. Private intent funded & unclaimed > 24h
    if (
        intent.receive_mode == "private"
        and intent.status == "funded"
        and (now_utc - updated_utc) > timedelta(hours=24)
    ):
        anomalies.append({
            "code": "private_unclaimed",
            "severity": "low",
            "message": "Private Umbra deposit has awaited merchant claim for over 24 hours.",
        })

    # Recommend safest first recovery step
    codes = {a["code"] for a in anomalies}
    recommended_action: str | None = None
    if "funded_without_payout" in codes or "payout_failed" in codes:
        recommended_action = "retry_payout"
    elif codes & {
        "expired_with_paid_rail",
        "payout_unlinked",
        "payout_delayed",
        "paj_tx_untracked",
        "paj_stuck",
        "paj_error",
    }:
        recommended_action = "reconcile"
    elif "duplicate_rail_payment" in codes or "direct_crypto_on_fiat_intent" in codes:
        recommended_action = "manual_review"

    return {
        "paidVia": paid_via,
        "settlementStatus": settlement_status,
        "anomalies": anomalies,
        "recommendedAction": recommended_action,
        "primaryPaj": primary_paj,
        "latestCheckout": latest_checkout,
        "latestPayout": latest_payout,
    }
