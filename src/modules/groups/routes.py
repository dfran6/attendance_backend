import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, require_admin, require_approved
from src.db.mains import get_session
from src.modules.groups import service
from src.modules.groups.schema import AreaCreate, AreaOut, GroupCreate, GroupOut, GroupUpdate, PublicGroupOut

group_router = APIRouter()
area_router = APIRouter()


@group_router.get("/public", response_model=List[PublicGroupOut])
async def public_groups(area_id: Optional[uuid.UUID] = None, session: AsyncSession = Depends(get_session)):
    """Unauthenticated: active groups for the registration form."""
    return await service.list_public_groups(session, area_id)


@group_router.get("", response_model=List[GroupOut])
async def managed_groups(principal: Principal = Depends(require_approved), session: AsyncSession = Depends(get_session)):
    """Groups the caller manages: their executive group, or all groups in their LGI areas."""
    return await service.list_managed_groups(principal, session)


@group_router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: uuid.UUID, principal: Principal = Depends(require_approved),
                    session: AsyncSession = Depends(get_session)):
    return await service.get_group_for_manager(group_id, principal, session)


@group_router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(data: GroupCreate, request: Request, principal: Principal = Depends(require_admin),
                       session: AsyncSession = Depends(get_session)):
    return await service.create_group(data, principal, request, session)


@group_router.patch("/{group_id}", response_model=GroupOut)
async def update_group(group_id: uuid.UUID, data: GroupUpdate, request: Request,
                       principal: Principal = Depends(require_approved), session: AsyncSession = Depends(get_session)):
    return await service.update_group(group_id, data, principal, request, session)


@area_router.get("", response_model=List[AreaOut])
async def list_areas(principal: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    return await service.list_areas(principal, session)


@area_router.post("", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
async def create_area(data: AreaCreate, request: Request, principal: Principal = Depends(require_admin),
                      session: AsyncSession = Depends(get_session)):
    return await service.create_area(data, principal, request, session)
