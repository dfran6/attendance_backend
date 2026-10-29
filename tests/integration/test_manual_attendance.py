"""Manual recording, corrections history, roster and personal history."""
from sqlmodel import select

from src.models import AttendanceCorrection, AuditLog
from src.models.enums import MembershipRole, SessionStatus


async def _setup(factory, make_client, status=SessionStatus.active):
    area = await factory.area()
    group = await factory.group(area)
    executive = await factory.member(group, role=MembershipRole.executive)
    member = await factory.member(group)
    other_member = await factory.member(group)
    cds = await factory.cds_session(group, executive, status=status)
    ex = await make_client()
    await ex.login(executive.email)
    return area, group, executive, member, other_member, cds, ex


async def test_manual_record_then_correction_keeps_history(make_client, factory, db):
    _, _, executive, member, _, cds, ex = await _setup(factory, make_client)

    res = await ex.post(f"/api/v1/sessions/{cds.id}/attendance/manual",
                        json={"userId": str(member.id), "status": "present", "reason": "Phone camera broken"})
    assert res.status_code == 200, res.text
    record = res.json()
    assert record["method"] == "manual" and record["recordedById"] == str(executive.id)

    fixed = await ex.patch(f"/api/v1/attendance/{record['id']}", json={"status": "excused", "reason": "Medical letter"})
    assert fixed.status_code == 200 and fixed.json()["status"] == "excused"

    history = (await ex.get(f"/api/v1/attendance/{record['id']}/corrections")).json()
    assert [(h["previousStatus"], h["newStatus"]) for h in history] == [(None, "present"), ("present", "excused")]
    assert history[1]["reason"] == "Medical letter"
    actions = (await db.exec(select(AuditLog.action))).all()
    assert "attendance.manual_recorded" in actions and "attendance.corrected" in actions


async def test_correction_requires_reason_and_change(make_client, factory):
    _, _, _, member, _, cds, ex = await _setup(factory, make_client)
    url = f"/api/v1/sessions/{cds.id}/attendance/manual"
    assert (await ex.post(url, json={"userId": str(member.id), "status": "present"})).status_code == 422
    await ex.post(url, json={"userId": str(member.id), "status": "present", "reason": "Signed register"})
    res = await ex.post(url, json={"userId": str(member.id), "status": "present", "reason": "again"})
    assert res.status_code == 409


async def test_executive_cannot_edit_own_attendance(make_client, factory):
    _, _, executive, _, _, cds, ex = await _setup(factory, make_client)
    res = await ex.post(f"/api/v1/sessions/{cds.id}/attendance/manual",
                        json={"userId": str(executive.id), "status": "present", "reason": "I was there"})
    assert res.status_code == 403


async def test_member_cannot_record_attendance(make_client, factory, db):
    _, _, _, member, other_member, cds, _ = await _setup(factory, make_client)
    c = await make_client()
    await c.login(member.email)
    res = await c.post(f"/api/v1/sessions/{cds.id}/attendance/manual",
                       json={"userId": str(other_member.id), "status": "present", "reason": "friend"})
    assert res.status_code == 403
    assert (await c.get(f"/api/v1/sessions/{cds.id}/attendance")).status_code == 403
    assert (await db.exec(select(AttendanceCorrection))).all() == []


async def test_non_member_and_frozen_sessions_rejected(make_client, factory):
    _, group, executive, member, _, _, ex = await _setup(factory, make_client)
    stranger = await factory.member(await factory.group(await factory.area()))
    active = await factory.cds_session(group, executive, status=SessionStatus.closed)
    res = await ex.post(f"/api/v1/sessions/{active.id}/attendance/manual",
                        json={"userId": str(stranger.id), "status": "present", "reason": "Wrong group"})
    assert res.status_code == 404
    for frozen in (SessionStatus.archived, SessionStatus.scheduled):
        s = await factory.cds_session(group, executive, status=frozen)
        res = await ex.post(f"/api/v1/sessions/{s.id}/attendance/manual",
                            json={"userId": str(member.id), "status": "present", "reason": "Late fix"})
        assert res.status_code == 409, frozen


async def test_roster_summary_counts_absent_after_close(make_client, factory):
    _, _, _, member, other_member, cds, ex = await _setup(factory, make_client)
    await ex.post(f"/api/v1/sessions/{cds.id}/attendance/manual",
                  json={"userId": str(member.id), "status": "excused", "reason": "Official duty"})

    live = (await ex.get(f"/api/v1/sessions/{cds.id}/attendance")).json()
    # 3 approved members: executive, member, other_member.
    assert live["summary"] == {"eligible": 3, "present": 0, "late": 0, "excused": 1, "absent": 0, "notRecorded": 2}

    await ex.post(f"/api/v1/sessions/{cds.id}/close")
    closed = (await ex.get(f"/api/v1/sessions/{cds.id}/attendance")).json()
    assert closed["summary"]["absent"] == 2 and closed["summary"]["excused"] == 1
    by_user = {e["userId"]: e["attendance"] for e in closed["entries"]}
    assert by_user[str(other_member.id)] is None


async def test_my_attendance_history(make_client, factory):
    _, _, _, member, _, cds, ex = await _setup(factory, make_client)
    await ex.post(f"/api/v1/sessions/{cds.id}/attendance/manual",
                  json={"userId": str(member.id), "status": "late", "reason": "Arrived after register"})
    c = await make_client()
    await c.login(member.email)
    page = (await c.get("/api/v1/attendance/me")).json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["sessionTitle"] == "Thursday CDS" and item["status"] == "late"
    # Members can read the history of their own record, but not others'.
    assert (await c.get(f"/api/v1/attendance/{item['id']}/corrections")).status_code == 200
    sessions = (await c.get("/api/v1/sessions")).json()["items"]
    assert sessions[0]["myStatus"] == "late"
