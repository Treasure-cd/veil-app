import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List
from core.session import get_session
from app.routers.dependencies import get_current_user
from app.models.user import User
from app.models.payroll import PayrollGroup, PayrollLink

router = APIRouter(
    prefix="/payroll",
    tags=["payroll"],
)

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

@router.post("/groups")
async def create_group(
    req: CreatePayrollGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session)
):
    now_str = datetime.utcnow().isoformat() + "Z"
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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO releaseAt timestamp")

    group = PayrollGroup(
        user_id=current_user.id,
        employer_ref=req.employerRef,
        title=req.title,
        token=req.token,
        release_at=release_at_dt,
        confirmation_window_hours=req.confirmationWindowHours,
        auto_proceed_after_confirmation_window=req.autoProceedAfterConfirmationWindow,
        registration_link_open=req.registrationLinkOpen,
        recipients_json=json.dumps(recipients_list),
        status="open" if req.registrationLinkOpen else "draft",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
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
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")
    
    return format_group(group)

@router.post("/groups/{group_id}/recipients")
async def add_recipient(
    group_id: str,
    req: AddRecipientRequest,
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []

    now_str = datetime.utcnow().isoformat() + "Z"
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
    group.updated_at = datetime.utcnow()

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_recipient(new_rec)

@router.post("/groups/{group_id}/registration-links")
async def create_registration_link(
    group_id: str,
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    token = str(uuid4())
    link = PayrollLink(
        token=token,
        payroll_id=uuid_id,
        open=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
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
    db: AsyncSession = Depends(get_session)
):
    stmt = select(PayrollLink).where(PayrollLink.token == token)
    res = await db.execute(stmt)
    link = res.scalars().first()

    if not link or not link.open:
        raise HTTPException(status_code=404, detail="link_not_found_or_closed")

    # Get group
    stmt_g = select(PayrollGroup).where(PayrollGroup.id == link.payroll_id)
    res_g = await db.execute(stmt_g)
    group = res_g.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    try:
        recipients = json.loads(group.recipients_json)
    except Exception:
        recipients = []

    now_str = datetime.utcnow().isoformat() + "Z"
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
    group.updated_at = datetime.utcnow()

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_recipient(new_rec)

@router.post("/groups/{group_id}/lock")
async def lock_vault(
    group_id: str,
    req: LockVaultRequest,
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    group.status = "locked"
    group.vault_signature = req.vaultSignature
    group.updated_at = datetime.utcnow()

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)

@router.post("/groups/{group_id}/schedule")
async def schedule_release(
    group_id: str,
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    group.status = "scheduled"
    group.updated_at = datetime.utcnow()

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)

@router.post("/groups/{group_id}/release")
async def release_payroll(
    group_id: str,
    req: ReleasePayrollRequest,
    db: AsyncSession = Depends(get_session)
):
    try:
        uuid_id = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID")

    stmt = select(PayrollGroup).where(PayrollGroup.id == uuid_id)
    res = await db.execute(stmt)
    group = res.scalars().first()

    if not group:
        raise HTTPException(status_code=404, detail="group_not_found")

    group.status = "released"
    group.release_signature = req.releaseSignature
    group.updated_at = datetime.utcnow()

    db.add(group)
    await db.commit()
    await db.refresh(group)
    return format_group(group)
