"""Attendance: QR check-in, rosters, personal history and audited manual changes.

Correctness under retries and concurrency comes from the (user_id, session_id) unique
constraint, not from Redis or client state: a second insert fails and is reported as
DUPLICATE_CHECKIN. Absence is derived (eligible member with no record), never stored.
"""
import math
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.exceptions import AppError, ErrorCode, conflict, forbidden, not_found
from src.core.permissions import Principal
from src.models import AttendanceCorrection, AttendanceRecord, CdsGroup, CdsSession, Membership, QrChallenge, User
from src.models.base import as_utc, utc_now
from src.models.enums import AttendanceStatus, MembershipStatus, SessionStatus, VerificationMethod
from src.modules.attendance.schema import (
    AttendanceOut,
    CheckInRequest,
    CheckInResponse,
    CorrectionOut,
    MyAttendanceItem,
    RosterEntry,
    RosterResponse,
    RosterSummary,
)
from src.modules.audit import service as audit
from src.modules.qr_codes.service import invalid_challenge, verify_challenge
from src.modules.sessions.service import activate_due_sessions, load_session
from src.shared.schemas import Page, PageParams

# GPS accuracy credited towards the geofence, capped so a vague fix can't stretch it far.
MAX_ACCURACY_ALLOWANCE_M = 50
EDITABLE_SESSION_STATES = (SessionStatus.active, SessionStatus.closed)


def _out(r: AttendanceRecord) -> AttendanceOut:
    return AttendanceOut(
        id=r.id, session_id=r.session_id, user_id=r.user_id, status=r.status, method=r.method,
        checked_in_at=as_utc(r.checked_in_at), recorded_by_id=r.recorded_by_id, distance_m=r.distance_m,
        updated_at=as_utc(r.updated_at),
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def _existing(user_id: uuid.UUID, session_id: uuid.UUID, db: AsyncSession, lock: bool = False):
    stmt = select(AttendanceRecord).where(AttendanceRecord.user_id == user_id, AttendanceRecord.session_id == session_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.exec(stmt)).first()


def _duplicate(record: AttendanceRecord) -> AppError:
    return conflict("You're already checked in to this session.", ErrorCode.DUPLICATE_CHECKIN,
                    {"status": record.status.value, "checkedInAt": as_utc(record.checked_in_at).isoformat()})


async def _reject(db: AsyncSession, principal: Principal, request: Request, reason: str, error: AppError,
                  session_id: Optional[uuid.UUID] = None, group: Optional[CdsGroup] = None) -> AppError:
    """Record a refused check-in for security review, then return the error to raise."""
    audit.record(db, "attendance.checkin_rejected", actor_id=principal.id, target_type="session",
                 target_id=session_id, group_id=group.id if group else None,
                 area_id=group.area_id if group else None, request=request, context={"reason": reason})
    await db.commit()
    return error


async def check_in(data: CheckInRequest, principal: Principal, request: Request, db: AsyncSession) -> CheckInResponse:
    try:
        challenge_id, session_id = verify_challenge(data.payload)
    except AppError as exc:
        raise await _reject(db, principal, request, exc.error_code.lower(), exc)

    await activate_due_sessions(session_id=session_id)
    challenge = await db.get(QrChallenge, challenge_id)
    if challenge is None or challenge.session_id != session_id:
        raise await _reject(db, principal, request, "unknown_challenge", invalid_challenge(), session_id)

    cds = await db.get(CdsSession, session_id)
    group = await db.get(CdsGroup, cds.group_id)
    if principal.approved_group_id != group.id:
        raise await _reject(db, principal, request, "wrong_group",
                            forbidden("This session belongs to a different CDS group."), cds.id, group)
    if cds.status != SessionStatus.active:
        raise AppError(409, ErrorCode.SESSION_NOT_ACTIVE, "This session isn't taking attendance right now.")

    existing = await _existing(principal.id, cds.id, db)
    if existing is not None:
        raise _duplicate(existing)

    distance = None
    if cds.radius_m is not None:
        if data.latitude is None or data.longitude is None:
            raise AppError(428, ErrorCode.LOCATION_REQUIRED, "This session needs your location to check you in.")
        distance = haversine_m(data.latitude, data.longitude, cds.latitude, cds.longitude)
        allowance = cds.radius_m + min(data.accuracy_m or 0, MAX_ACCURACY_ALLOWANCE_M)
        if distance > allowance:
            raise await _reject(
                db, principal, request, "out_of_bounds",
                AppError(403, ErrorCode.OUT_OF_BOUNDS,
                         "You appear to be outside the venue. Move closer or ask an executive to record you.",
                         {"distanceM": round(distance), "radiusM": cds.radius_m}),
                cds.id, group,
            )

    now = utc_now()
    late_after = as_utc(cds.actual_start) + timedelta(minutes=cds.late_after_minutes)
    record = AttendanceRecord(
        user_id=principal.id, session_id=cds.id, method=VerificationMethod.qr, challenge_id=challenge.id,
        status=AttendanceStatus.present if now <= late_after else AttendanceStatus.late,
        checked_in_at=now, distance_m=round(distance) if distance is not None else None,
    )
    # Capture plain values first: a rollback expires every ORM object in the session, and
    # lazily reloading an expired attribute is not allowed under asyncio.
    user_id, cds_id, title, group_name = principal.id, cds.id, cds.title, group.name
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request for the same member won the race.
        await db.rollback()
        raise _duplicate(await _existing(user_id, cds_id, db))
    return CheckInResponse(**_out(record).model_dump(), session_title=title, group_name=group_name)


async def my_attendance(principal: Principal, params: PageParams, db: AsyncSession) -> Page[MyAttendanceItem]:
    base = (
        select(AttendanceRecord, CdsSession, CdsGroup)
        .join(CdsSession, CdsSession.id == AttendanceRecord.session_id)
        .join(CdsGroup, CdsGroup.id == CdsSession.group_id)
        .where(AttendanceRecord.user_id == principal.id)
    )
    total = (await db.exec(select(func.count()).select_from(base.subquery()))).one()
    rows = (
        await db.exec(base.order_by(CdsSession.scheduled_start.desc()).offset(params.offset).limit(params.page_size))
    ).all()
    items = [
        MyAttendanceItem(
            id=r.id, session_id=s.id, session_title=s.title, session_status=s.status,
            scheduled_start=as_utc(s.scheduled_start), group_name=g.name, venue=s.venue, status=r.status,
            method=r.method, checked_in_at=as_utc(r.checked_in_at),
        )
        for r, s, g in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


async def roster(session_id: uuid.UUID, principal: Principal, db: AsyncSession) -> RosterResponse:
    cds, group = await load_session(session_id, principal, db, manage=True)
    members = (
        await db.exec(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.group_id == group.id, Membership.status == MembershipStatus.approved)
            .order_by(User.full_name)
            .limit(2000)
        )
    ).all()
    records = {r.user_id: r for r in (await db.exec(select(AttendanceRecord).where(AttendanceRecord.session_id == cds.id))).all()}

    counts = {s: 0 for s in AttendanceStatus}
    entries = []
    for m, u in members:
        rec = records.get(u.id)
        if rec:
            counts[rec.status] += 1
        entries.append(RosterEntry(user_id=u.id, full_name=u.full_name, state_code=u.state_code, role=m.role,
                                   attendance=_out(rec) if rec else None))
    recorded = sum(counts.values())
    not_recorded = len(members) - recorded
    summary = RosterSummary(
        eligible=len(members), present=counts[AttendanceStatus.present], late=counts[AttendanceStatus.late],
        excused=counts[AttendanceStatus.excused],
        # Once a session is closed, members with no record are absent.
        absent=counts[AttendanceStatus.absent] + (not_recorded if cds.status != SessionStatus.active else 0),
        not_recorded=not_recorded,
    )
    return RosterResponse(session_id=cds.id, session_status=cds.status, summary=summary, entries=entries)


async def set_status(session_id: uuid.UUID, user_id: uuid.UUID, new_status: AttendanceStatus, reason: str,
                     principal: Principal, request: Request, db: AsyncSession) -> AttendanceOut:
    """Create or correct a record. Every change appends an AttendanceCorrection row."""
    cds, group = await load_session(session_id, principal, db, manage=True)
    if cds.status not in EDITABLE_SESSION_STATES:
        raise conflict("Attendance can only be changed for active or closed sessions.", ErrorCode.INVALID_TRANSITION)
    if user_id == principal.id:
        raise forbidden("You can't change your own attendance. Ask another executive or your LGI.")
    member = (
        await db.exec(
            select(Membership).where(Membership.user_id == user_id, Membership.group_id == group.id,
                                     Membership.status == MembershipStatus.approved)
        )
    ).first()
    if member is None:
        raise not_found("Group member")

    record = await _existing(user_id, cds.id, db, lock=True)
    previous = record.status if record else None
    if previous == new_status:
        raise conflict(f"Attendance is already recorded as {new_status.value}.", ErrorCode.CONFLICT)

    if record is None:
        record = AttendanceRecord(user_id=user_id, session_id=cds.id, status=new_status,
                                  method=VerificationMethod.manual, recorded_by_id=principal.id)
    else:
        record.status, record.recorded_by_id, record.updated_at = new_status, principal.id, utc_now()
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise conflict("Attendance was just recorded by someone else. Refresh and try again.", ErrorCode.CONFLICT)

    db.add(AttendanceCorrection(attendance_id=record.id, changed_by_id=principal.id, previous_status=previous,
                                new_status=new_status, reason=reason))
    audit.record(db, "attendance.manual_recorded" if previous is None else "attendance.corrected",
                 actor_id=principal.id, target_type="attendance", target_id=record.id, group_id=group.id,
                 area_id=group.area_id, request=request,
                 context={"userId": str(user_id), "sessionId": str(cds.id),
                          "from": previous.value if previous else None, "to": new_status.value})
    await db.commit()
    await db.refresh(record)
    return _out(record)


async def correct(attendance_id: uuid.UUID, new_status: AttendanceStatus, reason: str, principal: Principal,
                  request: Request, db: AsyncSession) -> AttendanceOut:
    record = await db.get(AttendanceRecord, attendance_id)
    if record is None:
        raise not_found("Attendance record")
    return await set_status(record.session_id, record.user_id, new_status, reason, principal, request, db)


async def corrections(attendance_id: uuid.UUID, principal: Principal, db: AsyncSession):
    record = await db.get(AttendanceRecord, attendance_id)
    if record is None:
        raise not_found("Attendance record")
    if record.user_id != principal.id:
        await load_session(record.session_id, principal, db, manage=True)
    rows = (
        await db.exec(
            select(AttendanceCorrection, User)
            .join(User, User.id == AttendanceCorrection.changed_by_id)
            .where(AttendanceCorrection.attendance_id == record.id)
            .order_by(AttendanceCorrection.created_at)
        )
    ).all()
    return [
        CorrectionOut(id=c.id, previous_status=c.previous_status, new_status=c.new_status, reason=c.reason,
                      changed_by_id=u.id, changed_by_name=u.full_name, created_at=as_utc(c.created_at))
        for c, u in rows
    ]
