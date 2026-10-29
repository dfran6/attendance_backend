from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, load_principal
from src.models import AdminArea, CdsGroup, User
from src.modules.users.schema import AdminScope, MembershipSummary, MeResponse, UpdateMeRequest


async def build_me(user: User, session: AsyncSession, principal: Optional[Principal] = None) -> MeResponse:
    principal = principal or await load_principal(user, session)

    membership = None
    if principal.membership is not None:
        m = principal.membership
        group = await session.get(CdsGroup, m.group_id)
        membership = MembershipSummary(
            id=m.id, group_id=group.id, group_name=group.name, group_code=group.code, area_id=group.area_id,
            role=m.role, status=m.status, decision_reason=m.decision_reason,
        )

    scopes = []
    for r in principal.admin_roles:
        area = await session.get(AdminArea, r.area_id) if r.area_id else None
        scopes.append(AdminScope(role=r.role, area_id=r.area_id, area_name=area.name if area else None))

    return MeResponse(
        id=user.id, full_name=user.full_name, email=user.email, state_code=user.state_code, phone=user.phone,
        account_status=user.account_status, roles=principal.roles, membership=membership, admin_scopes=scopes,
        created_at=user.created_at,
    )


async def update_me(principal: Principal, data: UpdateMeRequest, session: AsyncSession) -> User:
    user = principal.user
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
