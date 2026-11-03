from sqlmodel import SQLModel, Field
from uuid import uuid4, UUID
from datetime import datetime
from typing import Optional

class PaymentIntent(SQLModel, table=True):
    __tablename__ = "payment_intents"
    id: UUID = Field(primary_key=True, default_factory=uuid4)
    user_id: UUID = Field(..., index=True)
    merchant_ref: str = Field(...)
    mint: str = Field(...)
    amount_atomic: str = Field(...)
    recipient_address: str = Field(...)
    receive_mode: str = Field(default="private") # "private" or "public"
    memo: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None)
    status: str = Field(default="created") # created, funded, claimed, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    fund_signature: Optional[str] = Field(default=None)
    claim_signature: Optional[str] = Field(default=None)
    source: Optional[str] = Field(default=None)  # whatsapp | qr | nfc | web
    failure_reason: Optional[str] = Field(default=None)
