from sqlmodel import SQLModel, Field
from uuid import uuid4, UUID
from datetime import datetime, timezone
from typing import Optional


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(SQLModel, table=True):
    id: UUID = Field(
        primary_key=True,
        default_factory=uuid4
    )

    address: str = Field(
        unique=True,
        index=True
    )

    nonce: Optional[str] = Field(default=None)

    nonce_expires_at: Optional[datetime] = Field(
        default=None
    )

    created_at: datetime = Field(
        default_factory=utc_now
    )

    updated_at: datetime = Field(
        default_factory=utc_now
    )