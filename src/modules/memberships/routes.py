import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, get_principal, require_approved
from src.db.mains import get_session
from src.models.enums import MembershipStatus
from src.modules.groups.service import get_group_for_manager
from src.modules.memberships import service
from src.modules.memberships.schema import MembershipOut, ReapplyRequest, RejectRequest, RoleChangeRequest
from src.shared.schemas import Page, PageParams

membership_router = APIRouter()


@membership_router.get("/groups/{group_id}/memberships", response_model=Page[MembershipOut])
async def list_memberships(
    group_id: uuid.UUID,
    status_filter: Optional[MembershipStatus] = Query(None, alias="status"),
    q: Optional[str] = Query(None, max_length=100),
    params: PageParams = Depends(),
    principal: Principal = Depends(require_approved),
    session: AsyncSession = Depends(get_session),
):
    group = await get_group_for_manager(group_id, principal, session)
    return await service.list_group_memberships(group, status_filter, q, params, session)


@membership_router.post("/memberships/{membership_id}/approve", response_model=MembershipOut)
async def approve(membership_id: uuid.UUID, request: Request, principal: Principal = Depends(require_approved),
                  session: AsyncSession = Depends(get_session)):
    return await service.approve(membership_id, principal, request, session)


@membership_router.post("/memberships/{membership_id}/reject", response_model=MembershipOut)
async def reject(membership_id: uuid.UUID, data: RejectRequest, request: Request,
                 principal: Principal = Depends(require_approved), session: AsyncSession = Depends(get_session)):
    return await service.reject(membership_id, data.reason, principal, request, session)


@membership_router.post("/memberships/{membership_id}/role", response_model=MembershipOut)
async def change_role(membership_id: uuid.UUID, data: RoleChangeRequest, request: Request,
                      principal: Principal = Depends(require_approved), session: AsyncSession = Depends(get_session)):
    return await service.change_role(membership_id, data.role, principal, request, session)


@membership_router.post("/memberships", response_model=MembershipOut, status_code=status.HTTP_201_CREATED)
async def reapply(data: ReapplyRequest, request: Request, principal: Principal = Depends(get_principal),
                  session: AsyncSession = Depends(get_session)):
    """For rejected users (or approved users who left) to request a group again."""
    return await service.reapply(data.group_id, principal, request, session)
