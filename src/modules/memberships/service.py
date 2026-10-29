"""Membership approval workflow.

pending  -> approved   (group executive or area LGI; also approves a pending account)
pending  -> rejected   (same; reason required; a pending account becomes rejected)
approved -> role change (area LGI only — executives cannot promote anyone)
rejected account -> re-apply to an active group (creates a new pending membership)
"""
import uuid
from typing import Optional, Tuple

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.exceptions import AppError, ErrorCode, conflict, forbidden, not_found
from src.core.permissions import Principal
from src.models import CdsGroup, Membership, User
from src.models.base import utc_now
from src.models.enums import AccountStatus, MembershipRole, MembershipStatus
from src.modules.audit import service as audit
from src.modules.memberships.schema import MembershipOut
from src.shared.schemas import Page, PageParams


def _out(m: Membership, u: User) -> MembershipOut:
    return MembershipOut(
        id=m.id, group_id=m.group_id, role=m.role, status=m.status, decided_at=m.decided_at,
        decision_reason=m.decision_reason, created_at=m.created_at, user_id=u.id, full_name=u.full_name,
        email=u.email, state_code=u.state_code, account_status=u.account_status,
    )


async def list_group_memberships(group: CdsGroup, status: Optional[MembershipStatus], q: Optional[str],
                                 params: PageParams, session: AsyncSession) -> Page[MembershipOut]:
    base = select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.group_id == group.id)
    if status:
        base = base.where(Membership.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.where(func.lower(User.full_name).like(like) | func.lower(User.state_code).like(like))
    total = (await session.exec(select(func.count()).select_from(base.subquery()))).one()
    rows = (
        await session.exec(base.order_by(Membership.created_at.desc()).offset(params.offset).limit(params.page_size))
    ).all()
    return Page(items=[_out(m, u) for m, u in rows], total=total, page=params.page, page_size=params.page_size)


async def _load_for_decision(membership_id: uuid.UUID, principal: Principal,
                             session: AsyncSession) -> Tuple[Membership, CdsGroup, User]:
    # Lock the row so two executives deciding at once cannot both succeed.
    membership = (
        await session.exec(select(Membership).where(Membership.id == membership_id).with_for_update())
    ).first()
    if membership is None:
        raise not_found("Membership")
    group = await session.get(CdsGroup, membership.group_id)
    if not principal.can_manage_group(group):
        # 404 rather than 403 so IDs from other groups can't be probed.
        raise not_found("Membership")
    if membership.user_id == principal.id:
        raise forbidden("You cannot decide on your own membership.")
    user = await session.get(User, membership.user_id)
    return membership, group, user


def _require_pending(m: Membership) -> None:
    if m.status != MembershipStatus.pending:
        raise conflict(f"This request has already been {m.status.value}.", ErrorCode.INVALID_TRANSITION)


async def approve(membership_id: uuid.UUID, principal: Principal, request: Request,
                  session: AsyncSession) -> MembershipOut:
    m, group, user = await _load_for_decision(membership_id, principal, session)
    _require_pending(m)
    m.status, m.decided_by_id, m.decided_at, m.decision_reason = MembershipStatus.approved, principal.id, utc_now(), None
    if user.account_status in (AccountStatus.pending, AccountStatus.rejected):
        user.account_status = AccountStatus.approved
    session.add_all([m, user])
    audit.record(session, "membership.approved", actor_id=principal.id, target_type="membership", target_id=m.id,
                 group_id=group.id, area_id=group.area_id, request=request, context={"userId": str(user.id)})
    await session.commit()
    return _out(m, user)


async def reject(membership_id: uuid.UUID, reason: str, principal: Principal, request: Request,
                 session: AsyncSession) -> MembershipOut:
    m, group, user = await _load_for_decision(membership_id, principal, session)
    _require_pending(m)
    m.status, m.decided_by_id, m.decided_at, m.decision_reason = MembershipStatus.rejected, principal.id, utc_now(), reason
    if user.account_status == AccountStatus.pending:
        user.account_status = AccountStatus.rejected
    session.add_all([m, user])
    audit.record(session, "membership.rejected", actor_id=principal.id, target_type="membership", target_id=m.id,
                 group_id=group.id, area_id=group.area_id, request=request, context={"userId": str(user.id)})
    await session.commit()
    return _out(m, user)


async def change_role(membership_id: uuid.UUID, role: MembershipRole, principal: Principal, request: Request,
                      session: AsyncSession) -> MembershipOut:
    m, group, user = await _load_for_decision(membership_id, principal, session)
    if not principal.can_oversee_area(group.area_id):
        raise forbidden("Only the area LGI can change executive roles.")
    if m.status != MembershipStatus.approved:
        raise conflict("Only approved members can be assigned a role.", ErrorCode.INVALID_TRANSITION)
    previous = m.role
    m.role = role
    session.add(m)
    audit.record(session, "membership.role_changed", actor_id=principal.id, target_type="membership",
                 target_id=m.id, group_id=group.id, area_id=group.area_id, request=request,
                 context={"userId": str(user.id), "from": previous.value, "to": role.value})
    await session.commit()
    return _out(m, user)


async def reapply(group_id: uuid.UUID, principal: Principal, request: Request, session: AsyncSession) -> MembershipOut:
    user = principal.user
    if principal.membership is not None:
        raise conflict("You already have an active or pending membership.", ErrorCode.INVALID_TRANSITION)
    if user.account_status == AccountStatus.suspended:
        raise forbidden("This account has been suspended.", ErrorCode.ACCOUNT_SUSPENDED)
    group = await session.get(CdsGroup, group_id)
    if group is None or not group.is_active:
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "Some fields are invalid.",
                       {"fields": {"groupId": "Select an active CDS group."}})
    m = Membership(user_id=user.id, group_id=group.id)
    if user.account_status == AccountStatus.rejected:
        user.account_status = AccountStatus.pending
    session.add_all([m, user])
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise conflict("You already have an active or pending membership.", ErrorCode.INVALID_TRANSITION)
    audit.record(session, "membership.requested", actor_id=user.id, target_type="membership", target_id=m.id,
                 group_id=group.id, area_id=group.area_id, request=request)
    await session.commit()
    return _out(m, user)
