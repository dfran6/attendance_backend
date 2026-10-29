import uuid
from datetime import datetime, timedelta
from typing import Optional

from pydantic import Field, model_validator

from src.models.enums import AttendanceStatus, SessionStatus
from src.shared.schemas import ApiModel

MAX_SESSION_LENGTH = timedelta(hours=12)


class _SessionFields(ApiModel):
    title: str = Field(min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    venue: Optional[str] = Field(default=None, max_length=200)
    scheduled_start: datetime
    scheduled_end: datetime
    late_after_minutes: int = Field(default=30, ge=0, le=240)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[int] = Field(default=None, ge=20, le=2000)

    @model_validator(mode="after")
    def _check(self):
        for name in ("scheduled_start", "scheduled_end"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must include a timezone offset.")
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("The session must end after it starts.")
        if self.scheduled_end - self.scheduled_start > MAX_SESSION_LENGTH:
            raise ValueError("A session can last at most 12 hours.")
        geo = (self.latitude, self.longitude, self.radius_m)
        if any(v is not None for v in geo) and not all(v is not None for v in geo):
            raise ValueError("Set latitude, longitude and radius together, or none of them.")
        return self


class SessionCreate(_SessionFields):
    group_id: uuid.UUID


class SessionUpdate(_SessionFields):
    """Full replacement of the editable fields; allowed only while scheduled."""


class SessionOut(ApiModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    title: str
    description: Optional[str] = None
    venue: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    late_after_minutes: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_m: Optional[int] = None
    requires_location: bool
    status: SessionStatus
    created_at: datetime
    can_manage: bool
    my_status: Optional[AttendanceStatus] = None


class ChallengeOut(ApiModel):
    challenge_id: uuid.UUID
    payload: str
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int
