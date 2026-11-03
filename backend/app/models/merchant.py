from sqlmodel import SQLModel, Field
from uuid import uuid4, UUID
from datetime import datetime
from typing import Optional
from enum import StrEnum

class OnboardingStage(StrEnum):
    """Model for merchant onboarding stage"""

    BUSINESS_NAME = "business_name"
    BUSINESS_TYPE = "business_type"
    WALLET_ADDRESS = "wallet_address"
    COMPLETED = "completed"


class Merchant(SQLModel, table=True):
    """Entity for local merchant"""

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    whatsapp_no: str = Field(..., unique=True, index=True)
    business_name: Optional[str] = Field(default=None)
    business_type: Optional[str] = Field(default=None)
    wallet_address: Optional[str] = Field(default=None)
    onboarding_stage: str = Field(default=OnboardingStage.BUSINESS_NAME)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)