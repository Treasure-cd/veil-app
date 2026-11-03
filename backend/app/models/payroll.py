from sqlmodel import SQLModel, Field
from uuid import uuid4, UUID
from datetime import datetime
from typing import Optional

class PayrollGroup(SQLModel, table=True):
    __tablename__ = "payroll_groups"
    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., index=True)
    employer_ref: str = Field(...)
    title: str = Field(...)
    token: str = Field(...) # "USDC" or "SOL"
    settlement_mode: str = Field(default="crypto")
    confirmation_window_hours: int = Field(default=2)
    release_at: datetime = Field(...)
    auto_proceed_after_confirmation_window: bool = Field(default=True)
    registration_link_open: bool = Field(default=False)
    recipients_json: str = Field(...) # serialized list of recipients
    status: str = Field(default="draft") # draft, open, locked, scheduled, released, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    vault_signature: Optional[str] = Field(default=None)
    release_signature: Optional[str] = Field(default=None)
    failure_reason: Optional[str] = Field(default=None)

class PayrollLink(SQLModel, table=True):
    __tablename__ = "payroll_links"
    token: str = Field(primary_key=True)
    id: UUID = Field(default_factory=uuid4)
    payroll_id: UUID = Field(..., index=True)
    open: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
