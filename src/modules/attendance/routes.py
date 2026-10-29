import uuid
from typing import List

from fastapi import APIRouter, Depends, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, require_approved
from src.core.rate_limiter import RateLimiter
from src.db.mains import get_session
from src.modules.attendance import service
from src.modules.attendance.schema import (
    AttendanceOut,
    CheckInRequest,
    CheckInResponse,
    CorrectionOut,
    CorrectionRequest,
    ManualAttendanceRequest,
    MyAttendanceItem,
    RosterResponse,
)
from src.shared.schemas import Page, PageParams

attendance_router = APIRouter()
session_attendance_router = APIRouter()

# Per user, not per IP: a whole venue may share one Wi-Fi address.
checkin_limiter = RateLimiter(max_requests=12, window_seconds=60, scope="checkin")


@attendance_router.post("/checkin", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
async def check_in(data: CheckInRequest, request: Request, principal: Principal = Depends(require_approved),
                   db: AsyncSession = Depends(get_session)):
    await checkin_limiter.check(f"user:{principal.id}")
    return await service.check_in(data, principal, request, db)


@attendance_router.get("/me", response_model=Page[MyAttendanceItem])
async def my_attendance(params: PageParams = Depends(), principal: Principal = Depends(require_approved),
                        db: AsyncSession = Depends(get_session)):
    return await service.my_attendance(principal, params, db)


@attendance_router.patch("/{attendance_id}", response_model=AttendanceOut)
async def correct(attendance_id: uuid.UUID, data: CorrectionRequest, request: Request,
                  principal: Principal = Depends(require_approved), db: AsyncSession = Depends(get_session)):
    return await service.correct(attendance_id, data.status, data.reason, principal, request, db)


@attendance_router.get("/{attendance_id}/corrections", response_model=List[CorrectionOut])
async def corrections(attendance_id: uuid.UUID, principal: Principal = Depends(require_approved),
                      db: AsyncSession = Depends(get_session)):
    """Change history: visible to the member it concerns and to the group's managers."""
    return await service.corrections(attendance_id, principal, db)


@session_attendance_router.get("/{session_id}/attendance", response_model=RosterResponse)
async def roster(session_id: uuid.UUID, principal: Principal = Depends(require_approved),
                 db: AsyncSession = Depends(get_session)):
    return await service.roster(session_id, principal, db)


@session_attendance_router.post("/{session_id}/attendance/manual", response_model=AttendanceOut)
async def manual(session_id: uuid.UUID, data: ManualAttendanceRequest, request: Request,
                 principal: Principal = Depends(require_approved), db: AsyncSession = Depends(get_session)):
    """Record or correct a member's attendance. A reason is mandatory and history is kept."""
    return await service.set_status(session_id, data.user_id, data.status, data.reason, principal, request, db)
