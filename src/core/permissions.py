"""Authentication and scope-based authorization dependencies.

Every protected route resolves a Principal, then services call the scope checks below
with the concrete resource (group/area) they are about to touch. Hiding UI is never
a substitute for these checks.
"""
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Set

from fastapi import Depends, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.exceptions import ErrorCode, forbidden, unauthorized
from src.core.security import TokenExpired, TokenInvalid, decode_access_token
from src.db.mains import get_session
from src.models import AuthSession, CdsGroup, Membership, RoleAssignment, User
from src.models.enums import AccountStatus, AdminRole, MembershipRole, MembershipStatus

ACCESS_COOKIE = "cds_access"


@dataclass
class Principal:
    user: User
    membership: Optional[Membership] = None  # the user's single pending/approved membership
    admin_roles: List[RoleAssignment] = field(default_factory=list)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def is_super_admin(self) -> bool:
        return any(r.role == AdminRole.super_admin for r in self.admin_roles)

    @property
    def lgi_area_ids(self) -> Set[uuid.UUID]:
        return {r.area_id for r in self.admin_roles if r.role == AdminRole.lgi and r.area_id}

    @property
    def approved_group_id(self) -> Optional[uuid.UUID]:
        m = self.membership
        return m.group_id if m and m.status == MembershipStatus.approved else None

    @property
    def executive_group_ids(self) -> Set[uuid.UUID]:
        m = self.membership
        if m and m.status == MembershipStatus.approved and m.role == MembershipRole.executive:
            return {m.group_id}
        return set()

    @property
    def roles(self) -> List[str]:
        roles = []
        if self.approved_group_id:
            roles.append("member")
        if self.executive_group_ids:
            roles.append("executive")
        if self.lgi_area_ids:
            roles.append("lgi")
        if self.is_super_admin:
            roles.append("super_admin")
        return roles

    # ---- scope checks -------------------------------------------------------------

    def can_oversee_area(self, area_id: uuid.UUID) -> bool:
        return self.is_super_admin or area_id in self.lgi_area_ids

    def can_manage_group(self, group: CdsGroup) -> bool:
        return group.id in self.executive_group_ids or self.can_oversee_area(group.area_id)

    def ensure_can_manage_group(self, group: CdsGroup) -> None:
        if not self.can_manage_group(group):
            raise forbidden()

    def ensure_can_oversee_area(self, area_id: uuid.UUID) -> None:
        if not self.can_oversee_area(area_id):
            raise forbidden()

    def ensure_admin(self) -> None:
        if not (self.is_super_admin or self.lgi_area_ids):
            raise forbidden()


def _extract_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(ACCESS_COOKIE)


async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = _extract_token(request)
    if not token:
        raise unauthorized()
    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
    except TokenExpired:
        raise unauthorized("Your session has expired.", ErrorCode.SESSION_EXPIRED)
    except (TokenInvalid, KeyError, ValueError):
        raise unauthorized("Invalid authentication token.")

    # Checking the backing refresh session makes logout/revocation take effect immediately.
    auth_session = await session.get(AuthSession, session_id)
    if auth_session is None or auth_session.user_id != user_id or auth_session.revoked_at is not None:
        raise unauthorized("Your session has ended. Please sign in again.", ErrorCode.SESSION_EXPIRED)

    user = await session.get(User, user_id)
    if user is None:
        raise unauthorized()
    if user.account_status == AccountStatus.suspended:
        raise forbidden("This account has been suspended.", ErrorCode.ACCOUNT_SUSPENDED)
    return user


async def load_principal(user: User, session: AsyncSession) -> Principal:
    membership = (
        await session.exec(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.status.in_([MembershipStatus.pending, MembershipStatus.approved]),
            )
        )
    ).first()
    roles = (
        await session.exec(
            select(RoleAssignment).where(RoleAssignment.user_id == user.id, RoleAssignment.revoked_at.is_(None))
        )
    ).all()
    return Principal(user=user, membership=membership, admin_roles=list(roles))


async def get_principal(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> Principal:
    """Any signed-in user, including pending ones (used by /users/me)."""
    return await load_principal(user, session)


async def require_approved(principal: Principal = Depends(get_principal)) -> Principal:
    """Signed-in and approved. Pending/rejected accounts cannot reach operational data."""
    status = principal.user.account_status
    if status == AccountStatus.pending:
        raise forbidden("Your account is awaiting approval.", ErrorCode.ACCOUNT_PENDING)
    if status == AccountStatus.rejected:
        raise forbidden("Your registration was not approved.", ErrorCode.ACCOUNT_REJECTED)
    return principal


async def require_admin(principal: Principal = Depends(require_approved)) -> Principal:
    principal.ensure_admin()
    return principal
