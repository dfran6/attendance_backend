import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import Field, field_validator

from src.models.enums import AccountStatus, AdminRole, MembershipRole, MembershipStatus
from src.shared.schemas import ApiModel


class MembershipSummary(ApiModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    group_code: str
    area_id: uuid.UUID
    role: MembershipRole
    status: MembershipStatus
    decision_reason: Optional[str] = None


class AdminScope(ApiModel):
    role: AdminRole
    area_id: Optional[uuid.UUID] = None
    area_name: Optional[str] = None


class MeResponse(ApiModel):
    id: uuid.UUID
    full_name: str
    email: str
    state_code: str
    phone: Optional[str] = None
    account_status: AccountStatus
    roles: List[str]
    membership: Optional[MembershipSummary] = None
    admin_scopes: List[AdminScope]
    created_at: datetime


class UpdateMeRequest(ApiModel):
    """Only self-service fields. Email and state code changes require an administrator."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: Optional[str]) -> Optional[str]:
        return " ".join(v.split()) if v is not None else v
