import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from solders.pubkey import Pubkey
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.payment import (
    FiatPayment,
    FiatPaymentFlow,
    FiatPaymentStatus,
    FossaPayWebhookEvent,
    MerchantBankAccount,
    PajOfframpOrder,
    PajOrderStatus,
    PaymentIntent,
    PaymentTraceEvent,
    SettlementTarget,
    utc_now,
)
from app.models.payroll import PayrollGroup
from app.models.user import User
from app.routers.dependencies import get_current_admin
from app.routers.payments import (
    _reconcile_intent_all_rails,
    _settle_fiat_intent_payout,
    format_bank_account,
    format_fiat_payment,
    format_paj_offramp,
    parse_uuid,
    verify_transfer,
    verify_umbra_deposit,
)
from app.services.trace import (
    SEED_ADMIN_ADDRESSES,
    compute_flow_assessment,
    record_trace_event,
)
from core.config import settings
from core.session import get_session

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)


class GrantAdminRequest(BaseModel):
    address: str = Field(min_length=32, max_length=64)
    note: Optional[str] = Field(default=None, max_length=255)

    @field_validator("address")
    @classmethod
    def validate_solana_address(cls, v: str) -> str:
        trimmed = v.strip()
        try:
            Pubkey.from_string(trimmed)
        except ValueError as exc:
            raise ValueError("Invalid Solana wallet address") from exc
        return trimmed


class AdminActionNoteRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class VerifySignatureRecoveryRequest(BaseModel):
    signature: str = Field(min_length=64, max_length=100)
    rail: Literal["direct", "paj", "umbra"] = "direct"
    pajOfframpOrderId: Optional[UUID] = None
    dryRun: bool = True
    ignoreExpiryWindow: bool = False
    note: Optional[str] = Field(default=None, max_length=500)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def _dec(value: str | Decimal | int | None) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _token_symbol(mint: str) -> str:
    if mint in settings.known_usdc_mints:
        return "USDC"
    if mint == settings.SOL_MINT:
        return "SOL"
    return "unknown"


def _token_amount(atomic: str, symbol: str) -> str:
    decimals = 6 if symbol == "USDC" else 9
    try:
        return format((Decimal(atomic) / (Decimal(10) ** decimals)).normalize(), "f")
    except Exception:
        return "0"


def _format_trace_event(event: PaymentTraceEvent) -> dict[str, Any]:
    details = None
    if event.details_json:
        try:
            details = json.loads(event.details_json)
        except Exception:
            details = {"raw": event.details_json}
    return {
        "id": str(event.id),
        "paymentIntentId": str(event.payment_intent_id) if event.payment_intent_id else None,
        "fiatPaymentId": str(event.fiat_payment_id) if event.fiat_payment_id else None,
        "pajOrderId": str(event.paj_order_id) if event.paj_order_id else None,
        "payrollGroupId": str(event.payroll_group_id) if event.payroll_group_id else None,
        "source": event.source,
        "eventType": event.event_type,
        "status": event.status,
        "summary": event.summary,
        "details": details,
        "actorAddress": event.actor_address,
        "createdAt": _utc_iso(event.created_at),
    }


def _format_admin_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "address": user.address,
        "isAdmin": bool(user.is_admin),
        "isSeedAdmin": user.address in SEED_ADMIN_ADDRESSES,
        "createdAt": _utc_iso(user.created_at),
        "updatedAt": _utc_iso(user.updated_at),
    }


async def _load_flow_context(db: AsyncSession, intents: list[PaymentIntent]):
    if not intents:
        return {}, {}, {}, {}, {}, {}

    intent_ids = [intent.id for intent in intents]
    user_ids = list({intent.user_id for intent in intents})
    bank_ids = list({intent.bank_account_id for intent in intents if intent.bank_account_id})

    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()
    user_by_id = {u.id: u for u in users}

    banks = (
        await db.execute(
            select(MerchantBankAccount).where(MerchantBankAccount.id.in_(bank_ids))
        )
    ).scalars().all() if bank_ids else []
    bank_by_id = {b.id: b for b in banks}

    fiat_rows = (
        await db.execute(
            select(FiatPayment)
            .where(FiatPayment.payment_intent_id.in_(intent_ids))
            .order_by(FiatPayment.created_at.desc())
        )
    ).scalars().all()
    checkouts_by_intent: dict[UUID, list[FiatPayment]] = {}
    payouts_by_intent: dict[UUID, list[FiatPayment]] = {}
    for row in fiat_rows:
        if row.payment_intent_id is None:
            continue
        if row.flow == FiatPaymentFlow.CHECKOUT.value:
            checkouts_by_intent.setdefault(row.payment_intent_id, []).append(row)
        elif row.flow == FiatPaymentFlow.PAYOUT.value:
            payouts_by_intent.setdefault(row.payment_intent_id, []).append(row)

    paj_rows = (
        await db.execute(
            select(PajOfframpOrder)
            .where(PajOfframpOrder.payment_intent_id.in_(intent_ids))
            .order_by(PajOfframpOrder.updated_at.desc(), PajOfframpOrder.created_at.desc())
        )
    ).scalars().all()
    paj_by_intent: dict[UUID, list[PajOfframpOrder]] = {}
    for row in paj_rows:
        if row.payment_intent_id is None:
            continue
        paj_by_intent.setdefault(row.payment_intent_id, []).append(row)

    trace_rows = (
        await db.execute(
            select(PaymentTraceEvent)
            .where(PaymentTraceEvent.payment_intent_id.in_(intent_ids))
            .order_by(PaymentTraceEvent.created_at.desc())
        )
    ).scalars().all()
    traces_by_intent: dict[UUID, list[PaymentTraceEvent]] = {}
    for event in trace_rows:
        if event.payment_intent_id is not None:
            traces_by_intent.setdefault(event.payment_intent_id, []).append(event)

    return (
        user_by_id,
        bank_by_id,
        checkouts_by_intent,
        payouts_by_intent,
        paj_by_intent,
        traces_by_intent,
    )


def _serialize_flow_summary(
    intent: PaymentIntent,
    *,
    merchant: User | None,
    bank: MerchantBankAccount | None,
    checkouts: list[FiatPayment],
    payouts: list[FiatPayment],
    paj_orders: list[PajOfframpOrder],
    traces: list[PaymentTraceEvent],
) -> dict[str, Any]:
    assessment = compute_flow_assessment(
        intent,
        checkouts=checkouts,
        payouts=payouts,
        paj_orders=paj_orders,
    )
    primary_paj = assessment["primaryPaj"]
    latest_checkout = assessment["latestCheckout"]
    latest_payout = assessment["latestPayout"]
    symbol = primary_paj.token_symbol if (primary_paj and primary_paj.token_symbol) else _token_symbol(intent.mint)
    token_amount = (
        primary_paj.token_amount
        if (primary_paj and primary_paj.token_amount)
        else _token_amount(intent.amount_atomic, symbol)
    )

    return {
        "id": str(intent.id),
        "merchantRef": intent.merchant_ref,
        "memo": intent.memo,
        "merchantAddress": merchant.address if merchant else None,
        "recipientAddress": intent.recipient_address,
        "channel": intent.source or "web",
        "receiveMode": intent.receive_mode,
        "settlementTarget": intent.settlement_target,
        "allowFiatCheckout": intent.allow_fiat_checkout,
        "intentStatus": intent.status,
        "failureReason": intent.failure_reason,
        "paidVia": assessment["paidVia"],
        "settlementStatus": assessment["settlementStatus"],
        "amountNgn": intent.amount_ngn,
        "token": symbol,
        "tokenAmount": token_amount,
        "rateNgnPerToken": intent.rate_ngn_per_token,
        "fundSignature": intent.fund_signature,
        "claimSignature": intent.claim_signature,
        "bankAccount": format_bank_account(bank, is_owner=True) if bank else None,
        "latestCheckout": format_fiat_payment(latest_checkout, is_owner=True) if latest_checkout else None,
        "latestPayout": format_fiat_payment(latest_payout, is_owner=True) if latest_payout else None,
        "primaryPaj": format_paj_offramp(primary_paj, is_owner=True) if primary_paj else None,
        "anomalies": assessment["anomalies"],
        "recommendedAction": assessment["recommendedAction"],
        "traceCount": len(traces),
        "latestTrace": _format_trace_event(traces[0]) if traces else None,
        "createdAt": _utc_iso(intent.created_at),
        "updatedAt": _utc_iso(intent.updated_at),
        "expiresAt": _utc_iso(intent.expires_at),
    }


async def _build_flow_detail(db: AsyncSession, intent: PaymentIntent) -> dict[str, Any]:
    merchant = await db.get(User, intent.user_id)
    bank = await db.get(MerchantBankAccount, intent.bank_account_id) if intent.bank_account_id else None
    fiat_rows = (
        await db.execute(
            select(FiatPayment)
            .where(FiatPayment.payment_intent_id == intent.id)
            .order_by(FiatPayment.created_at.desc())
        )
    ).scalars().all()
    checkouts = [r for r in fiat_rows if r.flow == FiatPaymentFlow.CHECKOUT.value]
    payouts = [r for r in fiat_rows if r.flow == FiatPaymentFlow.PAYOUT.value]
    paj_orders = (
        await db.execute(
            select(PajOfframpOrder)
            .where(PajOfframpOrder.payment_intent_id == intent.id)
            .order_by(PajOfframpOrder.created_at.desc())
        )
    ).scalars().all()
    traces = (
        await db.execute(
            select(PaymentTraceEvent)
            .where(PaymentTraceEvent.payment_intent_id == intent.id)
            .order_by(PaymentTraceEvent.created_at.desc())
        )
    ).scalars().all()

    refs = [r.reference for r in fiat_rows if r.reference]
    webhook_events = (
        await db.execute(
            select(FossaPayWebhookEvent)
            .where(FossaPayWebhookEvent.reference.in_(refs))
            .order_by(FossaPayWebhookEvent.received_at.desc())
        )
    ).scalars().all() if refs else []

    summary = _serialize_flow_summary(
        intent,
        merchant=merchant,
        bank=bank,
        checkouts=checkouts,
        payouts=payouts,
        paj_orders=paj_orders,
        traces=traces,
    )
    summary["checkouts"] = [format_fiat_payment(c, is_owner=True) for c in checkouts]
    summary["payouts"] = [format_fiat_payment(p, is_owner=True) for p in payouts]
    summary["pajOrders"] = [format_paj_offramp(o, is_owner=True) for o in paj_orders]
    summary["webhookEvents"] = [
        {
            "eventId": w.event_id,
            "eventType": w.event_type,
            "reference": w.reference,
            "receivedAt": _utc_iso(w.received_at),
        }
        for w in webhook_events
    ]
    summary["traces"] = [_format_trace_event(t) for t in traces]
    return summary


@router.get("/overview")
async def admin_overview(db: AsyncSession = Depends(get_session)):
    intents = (
        await db.execute(select(PaymentIntent).order_by(PaymentIntent.created_at.desc()))
    ).scalars().all()
    (
        _,
        _,
        checkouts_by_intent,
        payouts_by_intent,
        paj_by_intent,
        _,
    ) = await _load_flow_context(db, intents)

    total_volume_ngn = Decimal("0")
    settled_volume_ngn = Decimal("0")
    settling_volume_ngn = Decimal("0")
    status_counts = {
        "settled": 0,
        "settling": 0,
        "awaiting_claim": 0,
        "pending": 0,
        "expired": 0,
        "failed": 0,
    }
    rail_counts = {"fossapay": 0, "paj": 0, "crypto": 0, "unpaid": 0}
    anomaly_counts_by_code: dict[str, int] = {}
    anomalous_intents = 0

    for intent in intents:
        ngn = _dec(intent.amount_ngn)
        total_volume_ngn += ngn
        assessment = compute_flow_assessment(
            intent,
            checkouts=checkouts_by_intent.get(intent.id, []),
            payouts=payouts_by_intent.get(intent.id, []),
            paj_orders=paj_by_intent.get(intent.id, []),
        )
        s_status = assessment["settlementStatus"]
        status_counts[s_status] = status_counts.get(s_status, 0) + 1
        if s_status == "settled":
            settled_volume_ngn += ngn
        elif s_status in ("settling", "awaiting_claim"):
            settling_volume_ngn += ngn

        rail = assessment["paidVia"] or "unpaid"
        rail_counts[rail] = rail_counts.get(rail, 0) + 1

        if assessment["anomalies"]:
            anomalous_intents += 1
            for anomaly in assessment["anomalies"]:
                code = anomaly["code"]
                anomaly_counts_by_code[code] = anomaly_counts_by_code.get(code, 0) + 1

    unlinked_fiat_rows = (
        await db.execute(
            select(FiatPayment).where(FiatPayment.payment_intent_id.is_(None))
        )
    ).scalars().all()
    payroll_rows = (await db.execute(select(PayrollGroup))).scalars().all()
    all_users = (await db.execute(select(User))).scalars().all()
    trace_total = len((await db.execute(select(PaymentTraceEvent.id))).all())

    return {
        "network": settings.SOLANA_NETWORK,
        "totalIntents": len(intents),
        "totalVolumeNgn": format(total_volume_ngn, "f"),
        "settledVolumeNgn": format(settled_volume_ngn, "f"),
        "inFlightVolumeNgn": format(settling_volume_ngn, "f"),
        "statusCounts": status_counts,
        "railCounts": rail_counts,
        "anomalousIntentCount": anomalous_intents,
        "anomalyBreakdown": anomaly_counts_by_code,
        "unlinkedFiatCount": len(unlinked_fiat_rows),
        "payrollGroupCount": len(payroll_rows),
        "merchantCount": len(all_users),
        "adminCount": sum(1 for u in all_users if u.is_admin),
        "traceEventCount": trace_total,
    }


@router.get("/flows")
async def list_admin_flows(
    status: Literal[
        "all",
        "anomalies",
        "settled",
        "settling",
        "awaiting_claim",
        "pending",
        "expired",
        "failed",
    ] = Query(default="all"),
    rail: Literal["all", "paj", "fossapay", "crypto", "unpaid"] = Query(default="all"),
    q: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    intents = (
        await db.execute(select(PaymentIntent).order_by(PaymentIntent.created_at.desc()))
    ).scalars().all()
    (
        user_by_id,
        bank_by_id,
        checkouts_by_intent,
        payouts_by_intent,
        paj_by_intent,
        traces_by_intent,
    ) = await _load_flow_context(db, intents)

    needle = q.strip().lower() if q and q.strip() else None
    matched: list[dict[str, Any]] = []

    for intent in intents:
        checkouts = checkouts_by_intent.get(intent.id, [])
        payouts = payouts_by_intent.get(intent.id, [])
        paj_orders = paj_by_intent.get(intent.id, [])
        traces = traces_by_intent.get(intent.id, [])
        merchant = user_by_id.get(intent.user_id)
        bank = bank_by_id.get(intent.bank_account_id) if intent.bank_account_id else None
        row = _serialize_flow_summary(
            intent,
            merchant=merchant,
            bank=bank,
            checkouts=checkouts,
            payouts=payouts,
            paj_orders=paj_orders,
            traces=traces,
        )

        if status == "anomalies" and not row["anomalies"]:
            continue
        if status not in ("all", "anomalies") and row["settlementStatus"] != status:
            continue

        row_rail = row["paidVia"] or "unpaid"
        if rail != "all" and row_rail != rail:
            continue

        if needle:
            haystack = " ".join(
                str(part).lower()
                for part in (
                    row["id"],
                    row["merchantRef"],
                    row["memo"] or "",
                    row["merchantAddress"] or "",
                    row["recipientAddress"],
                    row["fundSignature"] or "",
                    row["claimSignature"] or "",
                    *(c.reference for c in checkouts),
                    *(c.account_number or "" for c in checkouts),
                    *(p.reference for p in payouts),
                    *(p.fossapay_id or "" for p in payouts),
                    *(o.paj_order_id or "" for o in paj_orders),
                    *(o.deposit_address or "" for o in paj_orders),
                    *(o.tx_signature or "" for o in paj_orders),
                )
            )
            if needle not in haystack:
                continue

        matched.append(row)

    total = len(matched)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": matched[offset : offset + limit],
    }


@router.get("/flows/{intent_id}")
async def get_admin_flow_detail(
    intent_id: str,
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")
    return await _build_flow_detail(db, intent)


@router.post("/flows/{intent_id}/reconcile")
async def admin_reconcile_flow(
    intent_id: str,
    body: Optional[AdminActionNoteRequest] = Body(default=None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    prior_status = intent.status
    prior_paid_via = intent.paid_via
    intent, _, _, _, _ = await _reconcile_intent_all_rails(db, intent)
    await record_trace_event(
        db,
        source="admin",
        event_type="admin_reconcile",
        summary=f"Admin ran multi-rail reconcile ({prior_status} -> {intent.status})",
        status="ok",
        payment_intent_id=intent.id,
        actor_address=admin.address,
        details={
            "priorStatus": prior_status,
            "newStatus": intent.status,
            "priorPaidVia": prior_paid_via,
            "newPaidVia": intent.paid_via,
            "note": body.note if body else None,
        },
        commit=True,
    )
    return await _build_flow_detail(db, intent)


@router.post("/flows/{intent_id}/verify-signature")
async def admin_verify_signature_recovery(
    intent_id: str,
    req: VerifySignatureRecoveryRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    dup_row = (
        await db.execute(
            select(PaymentIntent.id).where(PaymentIntent.fund_signature == req.signature)
        )
    ).first()
    duplicate_intent_id = str(dup_row[0]) if dup_row else None

    target_address = intent.recipient_address
    target_mint = intent.mint
    target_atomic = intent.amount_atomic
    offramp_order: PajOfframpOrder | None = None

    if req.rail == "paj":
        if req.pajOfframpOrderId is not None:
            offramp_order = await db.get(PajOfframpOrder, req.pajOfframpOrderId)
            if not offramp_order or offramp_order.payment_intent_id != intent.id:
                raise HTTPException(status_code=404, detail="paj_offramp_not_found")
        else:
            offramp_order = (
                await db.execute(
                    select(PajOfframpOrder)
                    .where(PajOfframpOrder.payment_intent_id == intent.id)
                    .order_by(PajOfframpOrder.created_at.desc())
                )
            ).scalars().first()
        if offramp_order is None or not offramp_order.token_amount:
            raise HTTPException(
                status_code=400,
                detail="No Paj offramp order with token amount exists for this payment.",
            )
        target_address = offramp_order.deposit_address
        target_mint = offramp_order.mint
        target_atomic = str(
            int(
                (Decimal(offramp_order.token_amount) * (Decimal(10) ** offramp_order.token_decimals)).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
        )

    before_ts = None if req.ignoreExpiryWindow else intent.expires_at
    if req.rail == "umbra" or intent.receive_mode == "private":
        matched_with_memo = await verify_umbra_deposit(
            req.signature,
            target_mint,
            target_atomic,
            intent.created_at,
            before=before_ts,
        )
        matched_amount_only = matched_with_memo
    else:
        matched_with_memo = await verify_transfer(
            req.signature,
            target_mint,
            target_address,
            target_atomic,
            intent.created_at,
            expected_memo=f"veil:{intent.id}",
            before=before_ts,
        )
        matched_amount_only = (
            True
            if matched_with_memo
            else await verify_transfer(
                req.signature,
                target_mint,
                target_address,
                target_atomic,
                intent.created_at,
                expected_memo=None,
                before=before_ts,
            )
        )

    applied = False
    if not req.dryRun:
        if duplicate_intent_id and duplicate_intent_id != str(intent.id):
            raise HTTPException(status_code=409, detail=f"Signature already used on intent {duplicate_intent_id}")
        if not matched_amount_only:
            raise HTTPException(status_code=400, detail="On-chain transfer does not match mint, destination, amount, and time window.")
        if intent.status not in ("created", "failed"):
            raise HTTPException(status_code=409, detail=f"Cannot overwrite intent in status '{intent.status}'")

        paid_via = "paj" if req.rail == "paj" else "crypto"
        intent.status = "funded"
        intent.failure_reason = None
        intent.fund_signature = req.signature
        intent.paid_via = paid_via
        intent.updated_at = utc_now()
        db.add(intent)
        if offramp_order is not None:
            offramp_order.tx_signature = req.signature
            if offramp_order.status == PajOrderStatus.INIT.value:
                offramp_order.status = PajOrderStatus.PROCESSING.value
            offramp_order.updated_at = utc_now()
            db.add(offramp_order)

        await record_trace_event(
            db,
            source="admin",
            event_type="admin_verify_signature",
            summary=f"Admin verified & applied {req.rail} signature {req.signature[:12]}...",
            status="ok",
            payment_intent_id=intent.id,
            paj_order_id=offramp_order.id if offramp_order else None,
            actor_address=admin.address,
            details={
                "signature": req.signature,
                "rail": req.rail,
                "matchedWithMemo": matched_with_memo,
                "ignoreExpiryWindow": req.ignoreExpiryWindow,
                "note": req.note,
            },
        )
        await db.commit()
        applied = True

    return {
        "dryRun": req.dryRun,
        "applied": applied,
        "matchedWithMemo": matched_with_memo,
        "matchedWithoutMemo": matched_amount_only,
        "duplicateIntentId": duplicate_intent_id,
        "targetAddress": target_address,
        "targetMint": target_mint,
        "targetAtomic": target_atomic,
        "flow": await _build_flow_detail(db, intent),
    }


@router.post("/flows/{intent_id}/retry-payout")
async def admin_retry_fiat_payout(
    intent_id: str,
    body: Optional[AdminActionNoteRequest] = Body(default=None),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    uuid_id = parse_uuid(intent_id)
    intent = await db.get(PaymentIntent, uuid_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")
    if intent.settlement_target != SettlementTarget.FIAT.value or not intent.bank_account_id:
        raise HTTPException(status_code=409, detail="This payment is not configured for fiat bank settlement.")

    checkout = (
        await db.execute(
            select(FiatPayment)
            .where(
                FiatPayment.payment_intent_id == intent.id,
                FiatPayment.flow == FiatPaymentFlow.CHECKOUT.value,
                FiatPayment.status == FiatPaymentStatus.COMPLETED.value,
            )
            .order_by(FiatPayment.created_at.desc())
        )
    ).scalars().first()
    if checkout is None:
        raise HTTPException(status_code=409, detail="No completed FossaPay checkout exists to disburse from.")

    payout = await _settle_fiat_intent_payout(
        db,
        intent,
        checkout,
        allow_retry=True,
        actor_address=admin.address,
    )
    if body and body.note:
        await record_trace_event(
            db,
            source="admin",
            event_type="admin_note",
            summary=f"Admin payout retry note: {body.note}",
            status="info",
            payment_intent_id=intent.id,
            fiat_payment_id=payout.id if payout else None,
            actor_address=admin.address,
            commit=True,
        )
    if payout is None:
        raise HTTPException(status_code=502, detail="Retry payout attempt failed; inspect trace log for FossaPay error.")
    return await _build_flow_detail(db, intent)


@router.get("/payroll")
async def list_admin_payroll(db: AsyncSession = Depends(get_session)):
    groups = (
        await db.execute(select(PayrollGroup).order_by(PayrollGroup.created_at.desc()))
    ).scalars().all()
    user_ids = list({g.user_id for g in groups})
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all() if user_ids else []
    user_by_id = {u.id: u for u in users}

    items = []
    for group in groups:
        try:
            recipients = json.loads(group.recipients_json or "[]")
        except Exception:
            recipients = []
        total_atomic = sum(int(r.get("amountAtomic") or 0) for r in recipients)
        total_ngn = sum(_dec(r.get("amountNgn")) for r in recipients)
        employer = user_by_id.get(group.user_id)
        items.append({
            "id": str(group.id),
            "employerAddress": employer.address if employer else None,
            "employerRef": group.employer_ref,
            "title": group.title,
            "token": group.token,
            "status": group.status,
            "recipientCount": len(recipients),
            "totalAmountNgn": format(total_ngn, "f"),
            "totalAmountToken": format((Decimal(total_atomic) / Decimal(10**9)).normalize(), "f") if total_atomic else "0",
            "vaultSignature": group.vault_signature,
            "releaseSignature": group.release_signature,
            "failureReason": group.failure_reason,
            "releaseAt": _utc_iso(group.release_at),
            "createdAt": _utc_iso(group.created_at),
        })
    return {"total": len(items), "items": items}


@router.get("/unlinked-fiat")
async def list_unlinked_fiat_payments(db: AsyncSession = Depends(get_session)):
    rows = (
        await db.execute(
            select(FiatPayment)
            .where(FiatPayment.payment_intent_id.is_(None))
            .order_by(FiatPayment.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    user_ids = list({r.user_id for r in rows})
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all() if user_ids else []
    user_by_id = {u.id: u for u in users}
    return {
        "total": len(rows),
        "items": [
            {
                **format_fiat_payment(row, is_owner=True),
                "userAddress": user_by_id[row.user_id].address if row.user_id in user_by_id else None,
            }
            for row in rows
        ],
    }


@router.get("/admins")
async def list_admins(db: AsyncSession = Depends(get_session)):
    admins = (
        await db.execute(
            select(User).where(User.is_admin == True).order_by(User.created_at.asc())  # noqa: E712
        )
    ).scalars().all()
    return {"items": [_format_admin_user(a) for a in admins]}


@router.post("/admins", status_code=201)
async def grant_admin(
    req: GrantAdminRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    target = (
        await db.execute(select(User).where(User.address == req.address))
    ).scalars().first()
    if target is None:
        target = User(address=req.address, is_admin=True)
    else:
        target.is_admin = True
        target.updated_at = utc_now()
    db.add(target)
    await db.flush()
    await record_trace_event(
        db,
        source="admin",
        event_type="admin_granted",
        summary=f"Admin privileges granted to {req.address}",
        status="ok",
        actor_address=admin.address,
        details={"targetAddress": req.address, "note": req.note},
    )
    await db.commit()
    await db.refresh(target)
    return _format_admin_user(target)


@router.delete("/admins/{address}")
async def revoke_admin(
    address: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    trimmed = address.strip()
    if trimmed in SEED_ADMIN_ADDRESSES:
        raise HTTPException(
            status_code=409,
            detail="Primary seed admin wallet cannot be revoked.",
        )
    if trimmed == admin.address:
        raise HTTPException(
            status_code=409,
            detail="You cannot revoke your own active admin session.",
        )
    target = (
        await db.execute(select(User).where(User.address == trimmed))
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="admin_not_found")
    if target.is_admin:
        target.is_admin = False
        target.updated_at = utc_now()
        db.add(target)
        await record_trace_event(
            db,
            source="admin",
            event_type="admin_revoked",
            summary=f"Admin privileges revoked from {trimmed}",
            status="warn",
            actor_address=admin.address,
            details={"targetAddress": trimmed},
        )
        await db.commit()
        await db.refresh(target)
    return _format_admin_user(target)
