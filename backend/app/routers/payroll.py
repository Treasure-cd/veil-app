import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Optional, List
from core.config import settings
from core.session import get_session
from app.routers.dependencies import get_current_user
from app.models.user import User
from app.models.payroll import PayrollGroup, PayrollLink
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature
from solders.transaction_status import TransactionConfirmationStatus

router = APIRouter(
    prefix="/payroll",
    tags=["payroll"],
)

# --- Models ---
class AddRecipientRequest(BaseModel):
    name: str
    walletAddress: str
    amountAtomic: Optional[str] = None
    memo: Optional[str] = None

class CreatePayrollGroupRequest(BaseModel):
    employerRef: str
    title: str
    token: str # USDC or SOL
    releaseAt: str
    confirmationWindowHours: int = 2
    autoProceedAfterConfirmationWindow: bool = True
    registrationLinkOpen: bool = False
    recipients: Optional[List[AddRecipientRequest]] = None

class LockVaultRequest(BaseModel):
    vaultSignature: str

class ReleasePayrollRequest(BaseModel):
    releaseSignature: str

class SubmitDetailsRequest(BaseModel):
    name: str
    walletAddress: str
    memo: Optional[str] = None

# --- Helpers ---
async def verify_solana_transaction(signature_str: str) -> bool:
    try:
        sig = Signature.from_string(signature_str)
        async with AsyncClient(settings.SOLANA_RPC_URL) as client:
            response = await client.get_signature_statuses(
                [sig],
                search_transaction_history=True,
            )
            if not response.value or not response.value[0]:
                return False
            transaction_status = response.value[0]
            return (
                transaction_status.err is None
                and transaction_status.confirmation_status
                in (
                    TransactionConfirmationStatus.Confirmed,
                    TransactionConfirmationStatus.Finalized,
                )
            )
    except Exception:
        return False

def format_recipient(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "walletAddress": r.get("walletAddress"),
        "amountAtomic": r.get("amountAtomic"),
        "memo": r.get("memo"),
        "registrationStatus": r.get("registrationStatus"),
        "createdAt": r.get("createdAt"),
        "updatedAt": r.get("updatedAt")
    }

def format_group(group: PayrollGroup) -> dict:
    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []

    total_amount = 0
    for r in recipients:
        if r.get("amountAtomic"):
            try:
                total_amount += int(r.get("amountAtomic"))
            except ValueError:
                pass

    return {
        "id": str(group.id),
        "userId": str(group.user_id),
        "employerRef": group.employer_ref,
        "title": group.title,
        "token": group.token,
        "settlementMode": group.settlement_mode,
        "confirmationWindowHours": group.confirmation_window_hours,
        "releaseAt": group.release_at.isoformat() + "Z" if isinstance(group.release_at, datetime) else group.release_at,
        "autoProceedAfterConfirmationWindow": group.auto_proceed_after_confirmation_window,
        "registrationLinkOpen": group.registration_link_open,
        "recipients": [format_recipient(r) for r in recipients],
        "status": group.status,
        "totalAmountAtomic": str(total_amount),
        "createdAt": group.created_at.isoformat() + "Z" if isinstance(group.created_at, datetime) else group.created_at,
        "updatedAt": group.updated_at.isoformat() + "Z" if isinstance(group.updated_at, datetime) else group.updated_at,
        "vaultSignature": group.vault_signature,
        "releaseSignature": group.release_signature,
        "failureReason": group.failure_reason
    }

# --- Routes ---
@router.post("/groups")
async def create_group(
    req: CreatePayrollGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    recipients_list = []
    if req.recipients:
        for r in req.recipients:
            recipients_list.append({
                "id": str(uuid4()),
                "name": r.name,
                "walletAddress": r.walletAddress,
                "amountAtomic": r.amountAtomic,
                "memo": r.memo,
                "registrationStatus": "submitted" if r.amountAtomic else "pending",
                "createdAt": now_str,
                "updatedAt": now_str
            })

    try:
        release_at_dt = datetime.fromisoformat(req.releaseAt.replace("Z", "+00:00"))
        # 1. Strip timezone from release_at right after parsing
        release_at_naive = release_at_dt.replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO releaseAt timestamp")

    # 2. Get current UTC time and strip the timezone for the DB
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    group = PayrollGroup(
        user_id=current_user.id,
        employer_ref=req.employerRef,
        title=req.title,
        token=req.token,
        # 3. Use the naive variables we just created
        release_at=release_at_naive,
        confirmation_window_hours=req.confirmationWindowHours,
        auto_proceed_after_confirmation_window=req.autoProceedAfterConfirmationWindow,
        registration_link_open=req.registrationLinkOpen,
        recipients_json=json.dumps(recipients_list),
        status="open" if req.registrationLinkOpen else "draft",
        created_at=now_naive,
        updated_at=now_naive
    )

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)

@router.get("/groups")
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    stmt = select(PayrollGroup).where(PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    groups = res.scalars().all()
    return [format_group(g) for g in groups]

@router.get("/groups/{group_id}")
async def get_group(
    group_id: str,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    return format_group(group)

@router.post("/groups/{group_id}/recipients")
async def add_recipient(
    group_id: str,
    req: AddRecipientRequest,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    uuid_id = UUID(group_id)
    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []

    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_rec = {
        "id": str(uuid4()),
        "name": req.name,
        "walletAddress": req.walletAddress,
        "amountAtomic": req.amountAtomic,
        "memo": req.memo,
        "registrationStatus": "submitted" if req.amountAtomic else "pending",
        "createdAt": now_str,
        "updatedAt": now_str
    }
    recipients.append(new_rec)
    group.recipients_json = json.dumps(recipients)
    group.updated_at = datetime.now(timezone.utc)

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_recipient(new_rec)

@router.post("/groups/{group_id}/registration-links")
async def create_registration_link(
    group_id: str,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    uuid_id = UUID(group_id)
    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
         raise HTTPException(status_code=404, detail="group_not_found")

    token = str(uuid4())
    link = PayrollLink(
        token=token,
        payroll_id=uuid_id,
        open=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(link)
    await db.commit()

    return {
        "payrollGroupId": group_id,
        "token": token,
        "link": f"/v1/payroll/registration-links/{token}"
    }

@router.post("/registration-links/{token}/submit")
async def submit_employee_details(
    token: str,
    req: SubmitDetailsRequest,
    db: AsyncSession = Depends(get_session) # NO AUTH - EMPLOYEES DON'T LOG IN
):
    stmt = select(PayrollLink).where(PayrollLink.token == token)
    res = await db.execute(stmt)
    link = res.scalars().first()

    if not link or not link.open:
        raise HTTPException(status_code=404, detail="link_not_found_or_closed")

    stmt_g = select(PayrollGroup).where(PayrollGroup.id == link.payroll_id)
    res_g = await db.execute(stmt_g)
    group = res_g.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    # STATE MACHINE CHECK: Can only submit if the group is open and not locked
    if not group.registration_link_open or group.status not in ["draft", "open"]:
         raise HTTPException(status_code=400, detail="Registration is closed for this payroll group")

    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []

    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    new_rec = {
        "id": str(uuid4()),
        "name": req.name,
        "walletAddress": req.walletAddress,
        "amountAtomic": None,
        "memo": req.memo,
        "registrationStatus": "submitted",
        "createdAt": now_str,
        "updatedAt": now_str
    }
    recipients.append(new_rec)
    group.recipients_json = json.dumps(recipients)
    group.updated_at = datetime.now(timezone.utc)

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_recipient(new_rec)

@router.post("/groups/{group_id}/lock")
async def lock_vault(
    group_id: str,
    req: LockVaultRequest,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    uuid_id = UUID(group_id)
    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    # STATE MACHINE
    if group.status not in ["draft", "open"]:
        raise HTTPException(status_code=400, detail="Can only lock a draft or open payroll group")

    # BLOCKCHAIN VERIFICATION
    is_valid_tx = await verify_solana_transaction(req.vaultSignature)
    if not is_valid_tx:
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    group.status = "locked"
    group.registration_link_open = False # Close registrations
    group.vault_signature = req.vaultSignature
    group.updated_at = datetime.now(timezone.utc)

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)

@router.post("/groups/{group_id}/schedule")
async def schedule_release(
    group_id: str,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    uuid_id = UUID(group_id)
    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    # STATE MACHINE
    if group.status != "locked":
        raise HTTPException(status_code=400, detail="Can only schedule a locked payroll group")

    group.status = "scheduled"
    group.updated_at = datetime.now(timezone.utc)

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)

@router.post("/groups/{group_id}/release")
async def release_payroll(
    group_id: str,
    req: ReleasePayrollRequest,
    current_user: User = Depends(get_current_user), # ADDED AUTH
    db: AsyncSession = Depends(get_session)
):
    uuid_id = UUID(group_id)
    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id, PayrollGroup.user_id == current_user.id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    # STATE MACHINE
    if group.status not in ["locked", "scheduled"]:
        raise HTTPException(status_code=400, detail="Can only release a locked or scheduled payroll group")

    # BLOCKCHAIN VERIFICATION
    is_valid_tx = await verify_solana_transaction(req.releaseSignature)
    if not is_valid_tx:
        raise HTTPException(status_code=400, detail="Transaction verification failed on-chain.")

    group.status = "released"
    group.release_signature = req.releaseSignature
    group.updated_at = datetime.now(timezone.utc)

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)
