from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppLink(SQLModel, table=True):
    __tablename__ = "whatsapp_links"

    id: int | None = Field(default=None, primary_key=True)
    merchant_id: UUID = Field(foreign_key="user.id", index=True)
    phone_e164: str = Field(sa_column=Column(String, unique=True, nullable=False, index=True))
    source: str = Field(default="code")
    linked_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class WhatsAppSession(SQLModel, table=True):
    __tablename__ = "whatsapp_sessions"

    phone_e164: str = Field(primary_key=True)
    state: str
    draft_memo: str | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class WhatsAppMessage(SQLModel, table=True):
    __tablename__ = "whatsapp_messages"

    message_sid: str = Field(primary_key=True)
    received_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    reply_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    replied_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class WhatsAppLinkCode(SQLModel, table=True):
    __tablename__ = "whatsapp_link_codes"

    code: str = Field(primary_key=True, max_length=6)
    merchant_id: UUID = Field(foreign_key="user.id", index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
