"""CDS session lifecycle.

scheduled -> active      automatically once scheduled_start arrives, or manually from
                         60 min before scheduled_start until scheduled_end
scheduled -> cancelled   cancel
active    -> closed      close   (QR challenges stop validating immediately)
closed    -> archived    archive (attendance becomes read-only)

Closed sessions are never reopened; late fixes use manual attendance corrections.
At most one session per group may be active (partial unique index).
"""
import uuid
from datetime import timedelta
from typing import Dict, List, Optional, Set

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.exceptions import AppError, ErrorCode, conflict, forbidden, not_found
from src.core.permissions import Principal
from src.db.mains import AsyncSessionLocal
from src.models import AttendanceRecord, CdsGroup, CdsSession, QrChallenge
from src.models.base import as_utc, utc_now
from src.models.enums import SessionStatus
from src.modules.audit import service as audit
from src.modules.qr_codes.service import challenge_ttl, sign_challenge
from src.modules.sessions.schema import ChallengeOut, SessionCreate, SessionOut, SessionUpdate
from src.shared.schemas import Page, PageParams

EARLY_START_WINDOW = timedelta(minutes=60)


async def activate_due_sessions(*, session_id: Optional[uuid.UUID] = None,
                                group_ids: Optional[Set[uuid.UUID]] = None) -> None:
    """Auto-start scheduled sessions whose start time has arrived (no worker needed: this runs
    whenever sessions are listed, opened or scanned).

    Uses its own short transaction so a lost race can never roll back or expire the caller's
    objects. Each row flips only if still `scheduled` (idempotent under concurrency), and a group
    that already has a live session is skipped rather than violating the one-active rule.
    """
    if group_ids is not None and not group_ids:
        return
    now = utc_now()
    async with AsyncSessionLocal() as s:
        stmt = (
            select(CdsSession.id, CdsSession.group_id, CdsSession.scheduled_start, CdsGroup.area_id)
            .join(CdsGroup, CdsGroup.id == CdsSession.group_id)
            .where(CdsSession.status == SessionStatus.scheduled, CdsSession.scheduled_start <= now,
                   CdsSession.scheduled_end > now)
            .order_by(CdsSession.scheduled_start)
        )
        if session_id is not None:
            stmt = stmt.where(CdsSession.id == session_id)
        if group_ids is not None:
            stmt = stmt.where(CdsSession.group_id.in_(group_ids))
        due = (await s.exec(stmt)).all()
        if not due:
            return
        busy = set((await s.exec(select(CdsSession.group_id).where(
            CdsSession.status == SessionStatus.active, CdsSession.group_id.in_({g for _, g, _, _ in due})))).all())
        for sid, gid, start, area_id in due:
            if gid in busy:
                continue
            result = await s.execute(
                update(CdsSession)
                .where(CdsSession.id == sid, CdsSession.status == SessionStatus.scheduled)
                .values(status=SessionStatus.active, actual_start=start, updated_at=now)
            )
            if result.rowcount:
                busy.add(gid)
                audit.record(s, "session.auto_started", target_type="session", target_id=sid, group_id=gid,
                             area_id=area_id)
        try:
            await s.commit()
        except IntegrityError:
            # A concurrent request started another session in the same group first. Harmless.
            await s.rollback()


def _reject_past(scheduled_end) -> None:
    if scheduled_end <= utc_now():
        raise AppError(422, ErrorCode.VALIDATION_ERROR, "Some fields are invalid.",
                       {"fields": {"scheduledEnd": "This time has already passed. Check the date, time and your device's time zone."}})


def to_out(s: CdsSession, group: CdsGroup, principal: Principal, my_status=None) -> SessionOut:
    return SessionOut(
        id=s.id, group_id=s.group_id, group_name=group.name, title=s.title, description=s.description,
        venue=s.venue, scheduled_start=as_utc(s.scheduled_start), scheduled_end=as_utc(s.scheduled_end),
        actual_start=as_utc(s.actual_start), actual_end=as_utc(s.actual_end),
        late_after_minutes=s.late_after_minutes, latitude=s.latitude, longitude=s.longitude, radius_m=s.radius_m,
        requires_location=s.radius_m is not None, status=s.status, created_at=as_utc(s.created_at),
        can_manage=principal.can_manage_group(group), my_status=my_status,
    )


async def accessible_group_ids(principal: Principal, session: AsyncSession) -> Optional[Set[uuid.UUID]]:
    """Groups whose sessions the principal may see. None means all (super admin)."""
    if principal.is_super_admin:
        return None
    ids: Set[uuid.UUID] = set(principal.executive_group_ids)
    if principal.approved_group_id:
        ids.add(principal.approved_group_id)
    if principal.lgi_area_ids:
        rows = await session.exec(select(CdsGroup.id).where(CdsGroup.area_id.in_(principal.lgi_area_ids)))
        ids.update(rows.all())
    return ids


async def load_session(session_id: uuid.UUID, principal: Principal, db: AsyncSession, *, manage: bool = False,
                       lock: bool = False):
    await activate_due_sessions(session_id=session_id)
    stmt = select(CdsSession).where(CdsSession.id == session_id)
    if lock:
        stmt = stmt.with_for_update()
    cds = (await db.exec(stmt)).first()
    if cds is None:
        raise not_found("Session")
    group = await db.get(CdsGroup, cds.group_id)
    if principal.can_manage_group(group):
        return cds, group
    if not manage and principal.approved_group_id == group.id:
        return cds, group
    # Members of the group get 403 for management actions; outsiders can't learn the ID exists.
    if principal.approved_group_id == group.id:
        raise forbidden()
    raise not_found("Session")


async def _my_statuses(user_id: uuid.UUID, session_ids: List[uuid.UUID], db: AsyncSession) -> Dict[uuid.UUID, str]:
    if not session_ids:
        return {}
    rows = await db.exec(
        select(AttendanceRecord.session_id, AttendanceRecord.status).where(
            AttendanceRecord.user_id == user_id, AttendanceRecord.session_id.in_(session_ids)
        )
    )
    return {sid: status for sid, status in rows.all()}


async def list_sessions(principal: Principal, group_id: Optional[uuid.UUID], status: Optional[SessionStatus],
                        params: PageParams, db: AsyncSession) -> Page[SessionOut]:
    allowed = await accessible_group_ids(principal, db)
    base = select(CdsSession, CdsGroup).join(CdsGroup, CdsGroup.id == CdsSession.group_id)
    if group_id:
        if allowed is not None and group_id not in allowed:
            raise forbidden()
        base = base.where(CdsSession.group_id == group_id)
    elif allowed is not None:
        base = base.where(CdsSession.group_id.in_(allowed or {uuid.UUID(int=0)}))
    if status:
        base = base.where(CdsSession.status == status)

    await activate_due_sessions(group_ids={group_id} if group_id else allowed)
    total = (await db.exec(select(func.count()).select_from(base.subquery()))).one()
    rows = (
        await db.exec(base.order_by(CdsSession.scheduled_start.desc()).offset(params.offset).limit(params.page_size))
    ).all()
    mine = await _my_statuses(principal.id, [s.id for s, _ in rows], db)
    return Page(
        items=[to_out(s, g, principal, mine.get(s.id)) for s, g in rows],
        total=total, page=params.page, page_size=params.page_size,
    )


async def get_session(session_id: uuid.UUID, principal: Principal, db: AsyncSession) -> SessionOut:
    # Start it if its scheduled time has arrived — the detail page polls this endpoint
    # expecting the flip, so it must activate just like the list view does.
    await activate_due_sessions(session_id=session_id)
    cds, group = await load_session(session_id, principal, db)
    mine = await _my_statuses(principal.id, [cds.id], db)
    return to_out(cds, group, principal, mine.get(cds.id))


async def create_session(data: SessionCreate, principal: Principal, request: Request, db: AsyncSession) -> SessionOut:
    group = await db.get(CdsGroup, data.group_id)
    if group is None or not principal.can_manage_group(group):
        raise forbidden()
    if not group.is_active:
        raise conflict("This group is inactive.", ErrorCode.INVALID_TRANSITION)
    _reject_past(data.scheduled_end)
    cds = CdsSession(created_by_id=principal.id, **data.model_dump())
    db.add(cds)
    await db.flush()
    audit.record(db, "session.created", actor_id=principal.id, target_type="session", target_id=cds.id,
                 group_id=group.id, area_id=group.area_id, request=request)
    await db.commit()
    return to_out(cds, group, principal)


def _require_status(cds: CdsSession, *allowed: SessionStatus) -> None:
    if cds.status not in allowed:
        raise conflict(f"This session is {cds.status.value}.", ErrorCode.INVALID_TRANSITION,
                       {"status": cds.status.value})


async def update_session(session_id: uuid.UUID, data: SessionUpdate, principal: Principal, request: Request,
                         db: AsyncSession) -> SessionOut:
    cds, group = await load_session(session_id, principal, db, manage=True, lock=True)
    _require_status(cds, SessionStatus.scheduled)
    _reject_past(data.scheduled_end)
    for field, value in data.model_dump().items():
        setattr(cds, field, value)
    db.add(cds)
    audit.record(db, "session.updated", actor_id=principal.id, target_type="session", target_id=cds.id,
                 group_id=group.id, area_id=group.area_id, request=request)
    await db.commit()
    await db.refresh(cds)
    return to_out(cds, group, principal)


async def transition(session_id: uuid.UUID, action: str, principal: Principal, request: Request,
                     db: AsyncSession) -> SessionOut:
    cds, group = await load_session(session_id, principal, db, manage=True, lock=True)
    now = utc_now()

    if action == "start":
        _require_status(cds, SessionStatus.scheduled)
        if now < as_utc(cds.scheduled_start) - EARLY_START_WINDOW:
            raise conflict("It's too early to start this session (up to 60 minutes before is allowed).",
                           ErrorCode.INVALID_TRANSITION)
        if now > as_utc(cds.scheduled_end):
            raise conflict("This session's scheduled time has passed. Cancel it or create a new one.",
                           ErrorCode.INVALID_TRANSITION)
        cds.status, cds.actual_start = SessionStatus.active, now
    elif action == "close":
        _require_status(cds, SessionStatus.active)
        cds.status, cds.actual_end = SessionStatus.closed, now
    elif action == "archive":
        _require_status(cds, SessionStatus.closed)
        cds.status = SessionStatus.archived
    elif action == "cancel":
        _require_status(cds, SessionStatus.scheduled)
        cds.status = SessionStatus.cancelled
    else:  # pragma: no cover - routes only pass known actions
        raise ValueError(action)

    db.add(cds)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise conflict("Another session is already active for this group. Close it first.",
                       ErrorCode.INVALID_TRANSITION)
    audit.record(db, f"session.{action}", actor_id=principal.id, target_type="session", target_id=cds.id,
                 group_id=group.id, area_id=group.area_id, request=request)
    await db.commit()
    await db.refresh(cds)
    return to_out(cds, group, principal)


async def issue_challenge(session_id: uuid.UUID, principal: Principal, db: AsyncSession) -> ChallengeOut:
    cds, _ = await load_session(session_id, principal, db, manage=True)
    if cds.status != SessionStatus.active:
        raise AppError(409, ErrorCode.SESSION_NOT_ACTIVE, "Start the session before showing the QR code.")
    issued = utc_now()
    challenge = QrChallenge(session_id=cds.id, issued_by_id=principal.id, issued_at=issued,
                            expires_at=issued + challenge_ttl())
    db.add(challenge)
    await db.commit()
    return ChallengeOut(
        challenge_id=challenge.id,
        payload=sign_challenge(challenge.id, cds.id, issued, challenge.expires_at),
        issued_at=issued, expires_at=challenge.expires_at, ttl_seconds=int(challenge_ttl().total_seconds()),
    )
