import uuid
from datetime import datetime
from typing import Optional

from pydantic import Field

from src.models.enums import AccountStatus, MembershipRole, MembershipStatus
from src.shared.schemas import ApiModel


class MembershipOut(ApiModel):
    id: uuid.UUID
    group_id: uuid.UUID
    role: MembershipRole
    status: MembershipStatus
    decided_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    created_at: datetime
    user_id: uuid.UUID
    full_name: str
    email: str
    state_code: str
    account_status: AccountStatus


class RejectRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=500)


class RoleChangeRequest(ApiModel):
    role: MembershipRole


class ReapplyRequest(ApiModel):
    group_id: uuid.UUID
