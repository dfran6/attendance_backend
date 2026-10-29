import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import Field, field_validator

from src.shared.schemas import ApiModel

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


def _code(v: str) -> str:
    v = v.strip().upper()
    if not _CODE_RE.match(v):
        raise ValueError("Use 2–32 letters, numbers, dashes or underscores.")
    return v


class AreaCreate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    code: str
    state: str = Field(min_length=2, max_length=64)

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _code(v)


class AreaOut(ApiModel):
    id: uuid.UUID
    name: str
    code: str
    state: str
    is_active: bool


class GroupCreate(ApiModel):
    area_id: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    code: str
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _code(v)


class GroupUpdate(ApiModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class PublicGroupOut(ApiModel):
    """Shown on the registration form — no member data."""

    id: uuid.UUID
    name: str
    code: str
    area_name: str


class GroupOut(ApiModel):
    id: uuid.UUID
    area_id: uuid.UUID
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
