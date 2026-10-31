import uuid
from datetime import datetime
from typing import Optional

from src.shared.schemas import ApiModel


class NotificationOut(ApiModel):
    id: uuid.UUID
    type: str
    title: str
    body: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class UnreadCount(ApiModel):
    count: int
