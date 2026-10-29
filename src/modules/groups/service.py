import uuid
from typing import List, Optional

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.exceptions import conflict, forbidden, not_found
from src.core.permissions import Principal
from src.models import AdminArea, CdsGroup
from src.modules.audit import service as audit
from src.modules.groups.schema import AreaCreate, GroupCreate, GroupUpdate, PublicGroupOut


async def list_public_groups(session: AsyncSession, area_id: Optional[uuid.UUID] = None) -> List[PublicGroupOut]:
    stmt = (
        select(CdsGroup, AdminArea)
        .join(AdminArea, AdminArea.id == CdsGroup.area_id)
        .where(CdsGroup.is_active.is_(True), AdminArea.is_active.is_(True))
        .order_by(CdsGroup.name)
        .limit(500)
    )
    if area_id:
        stmt = stmt.where(CdsGroup.area_id == area_id)
    rows = (await session.exec(stmt)).all()
    return [PublicGroupOut(id=g.id, name=g.name, code=g.code, area_name=a.name) for g, a in rows]


async def list_managed_groups(principal: Principal, session: AsyncSession) -> List[CdsGroup]:
    stmt = select(CdsGroup).order_by(CdsGroup.name)
    if not principal.is_super_admin:
        stmt = stmt.where(
            CdsGroup.area_id.in_(principal.lgi_area_ids or {uuid.UUID(int=0)})
            | CdsGroup.id.in_(principal.executive_group_ids or {uuid.UUID(int=0)})
        )
    return list((await session.exec(stmt)).all())


async def get_group_for_manager(group_id: uuid.UUID, principal: Principal, session: AsyncSession) -> CdsGroup:
    group = await session.get(CdsGroup, group_id)
    if group is None:
        raise not_found("Group")
    principal.ensure_can_manage_group(group)
    return group


async def list_areas(principal: Principal, session: AsyncSession) -> List[AdminArea]:
    stmt = select(AdminArea).order_by(AdminArea.name)
    if not principal.is_super_admin:
        stmt = stmt.where(AdminArea.id.in_(principal.lgi_area_ids or {uuid.UUID(int=0)}))
    return list((await session.exec(stmt)).all())


async def create_area(data: AreaCreate, principal: Principal, request: Request, session: AsyncSession) -> AdminArea:
    if not principal.is_super_admin:
        raise forbidden()
    area = AdminArea(name=data.name, code=data.code, state=data.state)
    session.add(area)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise conflict("An area with this code already exists.", details={"fields": {"code": "Already in use."}})
    audit.record(session, "area.created", actor_id=principal.id, target_type="area", target_id=area.id,
                 area_id=area.id, request=request)
    await session.commit()
    return area


async def create_group(data: GroupCreate, principal: Principal, request: Request, session: AsyncSession) -> CdsGroup:
    principal.ensure_can_oversee_area(data.area_id)
    if await session.get(AdminArea, data.area_id) is None:
        raise not_found("Area")
    group = CdsGroup(area_id=data.area_id, name=data.name, code=data.code, description=data.description)
    session.add(group)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise conflict("A group with this name or code already exists.")
    audit.record(session, "group.created", actor_id=principal.id, target_type="group", target_id=group.id,
                 group_id=group.id, area_id=group.area_id, request=request)
    await session.commit()
    return group


async def update_group(group_id: uuid.UUID, data: GroupUpdate, principal: Principal, request: Request,
                       session: AsyncSession) -> CdsGroup:
    group = await session.get(CdsGroup, group_id)
    if group is None:
        raise not_found("Group")
    # Executives may edit their group's description; renaming/deactivating is an area-level decision.
    changes = data.model_dump(exclude_unset=True)
    if set(changes) - {"description"}:
        principal.ensure_can_oversee_area(group.area_id)
    else:
        principal.ensure_can_manage_group(group)
    for field, value in changes.items():
        setattr(group, field, value)
    session.add(group)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise conflict("A group with this name already exists in this area.")
    audit.record(session, "group.updated", actor_id=principal.id, target_type="group", target_id=group.id,
                 group_id=group.id, area_id=group.area_id, request=request, context={"fields": sorted(changes)})
    await session.commit()
    await session.refresh(group)
    return group
