import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Column, DateTime, Index
from sqlmodel import Field, SQLModel

from src.models.base import created_at_field, id_field, timestamp_field, utc_now


class AuditLog(SQLModel, table=True):
    """Append-only. Never store passwords, tokens, or medical detail in `context`."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_group_created", "group_id", "created_at"),
        Index("ix_audit_logs_area_created", "area_id", "created_at"),
    )

    id: uuid.UUID = id_field()
    actor_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True, index=True)
    action: str = Field(max_length=64, nullable=False, index=True)
    target_type: Optional[str] = Field(default=None, max_length=64)
    target_id: Optional[str] = Field(default=None, max_length=64)
    area_id: Optional[uuid.UUID] = Field(default=None, nullable=True)
    group_id: Optional[uuid.UUID] = Field(default=None, nullable=True)
    request_id: Optional[str] = Field(default=None, max_length=64)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    context: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)
    )


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_recipient_read", "recipient_id", "read_at"),)

    id: uuid.UUID = id_field()
    recipient_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    type: str = Field(max_length=64, nullable=False)
    entity_type: Optional[str] = Field(default=None, max_length=64)
    entity_id: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(max_length=160, nullable=False)
    body: Optional[str] = Field(default=None, max_length=1000)
    read_at: Optional[datetime] = timestamp_field()
    created_at: datetime = created_at_field()
