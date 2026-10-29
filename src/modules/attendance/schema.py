import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import Field, model_validator

from src.models.enums import AttendanceStatus, MembershipRole, SessionStatus, VerificationMethod
from src.shared.schemas import ApiModel


class CheckInRequest(ApiModel):
    payload: str = Field(min_length=10, max_length=2048)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def _pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Send latitude and longitude together.")
        return self


class AttendanceOut(ApiModel):
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    status: AttendanceStatus
    method: VerificationMethod
    checked_in_at: datetime
    recorded_by_id: Optional[uuid.UUID] = None
    distance_m: Optional[int] = None
    updated_at: datetime


class CheckInResponse(AttendanceOut):
    session_title: str
    group_name: str


class MyAttendanceItem(ApiModel):
    id: uuid.UUID
    session_id: uuid.UUID
    session_title: str
    session_status: SessionStatus
    scheduled_start: datetime
    group_name: str
    venue: Optional[str] = None
    status: AttendanceStatus
    method: VerificationMethod
    checked_in_at: datetime


class RosterEntry(ApiModel):
    user_id: uuid.UUID
    full_name: str
    state_code: str
    role: MembershipRole
    attendance: Optional[AttendanceOut] = None


class RosterSummary(ApiModel):
    eligible: int
    present: int
    late: int
    excused: int
    absent: int
    not_recorded: int


class RosterResponse(ApiModel):
    session_id: uuid.UUID
    session_status: SessionStatus
    summary: RosterSummary
    entries: List[RosterEntry]


class ManualAttendanceRequest(ApiModel):
    user_id: uuid.UUID
    status: AttendanceStatus
    reason: str = Field(min_length=3, max_length=500)


class CorrectionRequest(ApiModel):
    status: AttendanceStatus
    reason: str = Field(min_length=3, max_length=500)


class CorrectionOut(ApiModel):
    id: uuid.UUID
    previous_status: Optional[AttendanceStatus] = None
    new_status: AttendanceStatus
    reason: str
    changed_by_id: uuid.UUID
    changed_by_name: str
    created_at: datetime
