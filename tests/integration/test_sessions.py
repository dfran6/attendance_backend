"""Session lifecycle and scope."""
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from src.models import AuditLog
from src.models.enums import MembershipRole, SessionStatus


def body(group_id, start=None, **over):
    start = start or datetime.now(timezone.utc) + timedelta(minutes=30)
    b = {
        "groupId": str(group_id),
        "title": "Thursday CDS",
        "venue": "LGA Hall",
        "scheduledStart": start.isoformat(),
        "scheduledEnd": (start + timedelta(hours=3)).isoformat(),
    }
    b.update(over)
    return b


async def _exec_setup(factory):
    area = await factory.area()
    group = await factory.group(area)
    other = await factory.group(area, "Education")
    executive = await factory.member(group, role=MembershipRole.executive)
    return area, group, other, executive


async def test_full_lifecycle_is_audited(client, factory, db):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)

    created = await client.post("/api/v1/sessions", json=body(group.id))
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["status"] == "scheduled" and created.json()["canManage"] is True

    for action, expected in [("start", "active"), ("close", "closed"), ("archive", "archived")]:
        res = await client.post(f"/api/v1/sessions/{sid}/{action}")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == expected
    actions = set((await db.exec(select(AuditLog.action))).all())
    assert {"session.created", "session.start", "session.close", "session.archive"} <= actions


async def test_invalid_transitions_are_rejected(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)
    sid = (await client.post("/api/v1/sessions", json=body(group.id))).json()["id"]

    for action in ("close", "archive"):
        res = await client.post(f"/api/v1/sessions/{sid}/{action}")
        assert res.status_code == 409 and res.json()["errorCode"] == "INVALID_TRANSITION"
    assert (await client.post(f"/api/v1/sessions/{sid}/cancel")).json()["status"] == "cancelled"
    assert (await client.post(f"/api/v1/sessions/{sid}/start")).status_code == 409


async def test_start_window(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)
    far = datetime.now(timezone.utc) + timedelta(hours=5)
    sid = (await client.post("/api/v1/sessions", json=body(group.id, start=far))).json()["id"]
    res = await client.post(f"/api/v1/sessions/{sid}/start")
    assert res.status_code == 409 and "too early" in res.json()["message"]


async def test_only_one_active_session_per_group(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await factory.cds_session(group, executive, status=SessionStatus.active)
    await client.login(executive.email)
    sid = (await client.post("/api/v1/sessions", json=body(group.id))).json()["id"]
    res = await client.post(f"/api/v1/sessions/{sid}/start")
    assert res.status_code == 409 and "already active" in res.json()["message"]


async def test_validation(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)
    start = datetime.now(timezone.utc)
    res = await client.post("/api/v1/sessions", json=body(group.id, scheduledEnd=(start - timedelta(hours=1)).isoformat()))
    assert res.status_code == 422
    res = await client.post("/api/v1/sessions", json=body(group.id, latitude=6.5, longitude=3.3))
    assert res.status_code == 422  # geofence needs radius too
    res = await client.post("/api/v1/sessions", json=body(group.id, scheduledStart="2026-11-05T10:00:00",
                                                          scheduledEnd="2026-11-05T12:00:00"))
    assert res.status_code == 422  # timezone required


async def test_edits_allowed_while_scheduled_or_live(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)
    sid = (await client.post("/api/v1/sessions", json=body(group.id))).json()["id"]
    patch = {k: v for k, v in body(group.id, title="Renamed").items() if k != "groupId"}
    # Scheduled: editable.
    assert (await client.patch(f"/api/v1/sessions/{sid}", json=patch)).json()["title"] == "Renamed"
    # Live: still editable (e.g. extend the end time).
    await client.post(f"/api/v1/sessions/{sid}/start")
    live = {k: v for k, v in body(group.id, title="Renamed live").items() if k != "groupId"}
    assert (await client.patch(f"/api/v1/sessions/{sid}", json=live)).json()["title"] == "Renamed live"
    # Closed: no longer editable.
    await client.post(f"/api/v1/sessions/{sid}/close")
    assert (await client.patch(f"/api/v1/sessions/{sid}", json=live)).status_code == 409


async def test_executive_cannot_manage_another_group(client, factory):
    _, group, other, executive = await _exec_setup(factory)
    other_exec = await factory.member(other, role=MembershipRole.executive)
    foreign = await factory.cds_session(other, other_exec)
    await client.login(executive.email)

    assert (await client.post("/api/v1/sessions", json=body(other.id))).status_code == 403
    for path in ("", "/start", "/challenges", "/attendance"):
        method = client.get if path in ("", "/attendance") else client.post
        assert (await method(f"/api/v1/sessions/{foreign.id}{path}")).status_code == 404, path
    assert (await client.get("/api/v1/sessions", params={"groupId": str(other.id)})).status_code == 403


async def test_members_see_own_group_sessions_but_cannot_manage(client, factory):
    _, group, other, executive = await _exec_setup(factory)
    member = await factory.member(group)
    mine = await factory.cds_session(group, executive)
    other_exec = await factory.member(other, role=MembershipRole.executive)
    await factory.cds_session(other, other_exec)

    await client.login(member.email)
    listing = (await client.get("/api/v1/sessions")).json()
    assert [s["id"] for s in listing["items"]] == [str(mine.id)]
    assert listing["items"][0]["canManage"] is False
    assert (await client.post(f"/api/v1/sessions/{mine.id}/start")).status_code == 403
    assert (await client.post("/api/v1/sessions", json=body(group.id))).status_code == 403


async def test_lgi_manages_sessions_in_area(client, factory):
    area, group, _, executive = await _exec_setup(factory)
    lgi = await factory.lgi(area)
    cds = await factory.cds_session(group, executive)
    await client.login(lgi.email)
    assert (await client.post(f"/api/v1/sessions/{cds.id}/start")).json()["status"] == "active"


async def test_challenge_requires_active_session(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    cds = await factory.cds_session(group, executive)
    await client.login(executive.email)
    res = await client.post(f"/api/v1/sessions/{cds.id}/challenges")
    assert res.status_code == 409 and res.json()["errorCode"] == "SESSION_NOT_ACTIVE"
    await client.post(f"/api/v1/sessions/{cds.id}/start")
    res = await client.post(f"/api/v1/sessions/{cds.id}/challenges")
    assert res.status_code == 201
    assert res.json()["payload"].startswith("CDSA1.") and res.json()["ttlSeconds"] == 20


# ---- auto-start & past-time validation ---------------------------------------------------

async def test_creating_a_session_in_the_past_is_rejected(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    await client.login(executive.email)
    past = datetime.now(timezone.utc) - timedelta(hours=9)  # e.g. a device clock in the wrong zone
    res = await client.post("/api/v1/sessions", json=body(group.id, start=past))
    assert res.status_code == 422
    assert "already passed" in res.json()["details"]["fields"]["scheduledEnd"]


async def test_due_session_auto_starts_when_viewed(client, factory, db):
    _, group, _, executive = await _exec_setup(factory)
    member = await factory.member(group)
    cds = await factory.cds_session(group, executive, starts_in=timedelta(minutes=-5))
    await client.login(member.email)

    listed = (await client.get("/api/v1/sessions")).json()["items"][0]
    assert listed["status"] == "active"
    # Lateness is measured from the *scheduled* start, not from whenever someone first looked.
    assert listed["actualStart"][:16] == listed["scheduledStart"][:16]
    assert "session.auto_started" in (await db.exec(select(AuditLog.action))).all()
    detail = (await client.get(f"/api/v1/sessions/{cds.id}")).json()
    assert detail["status"] == "active"


async def test_future_and_expired_sessions_do_not_auto_start(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    future = await factory.cds_session(group, executive, starts_in=timedelta(minutes=20))
    ended = await factory.cds_session(group, executive, starts_in=timedelta(hours=-5))  # ended 2h ago
    await client.login(executive.email)
    assert (await client.get(f"/api/v1/sessions/{future.id}")).json()["status"] == "scheduled"
    assert (await client.get(f"/api/v1/sessions/{ended.id}")).json()["status"] == "scheduled"


async def test_auto_start_skips_group_with_live_session(client, factory):
    _, group, _, executive = await _exec_setup(factory)
    live = await factory.cds_session(group, executive, status=SessionStatus.active)
    due = await factory.cds_session(group, executive, starts_in=timedelta(minutes=-5))
    await client.login(executive.email)
    assert (await client.get(f"/api/v1/sessions/{due.id}")).json()["status"] == "scheduled"
    assert (await client.get(f"/api/v1/sessions/{live.id}")).json()["status"] == "active"


async def test_check_in_late_relative_to_scheduled_start(make_client, factory):
    _, group, _, executive = await _exec_setup(factory)
    member = await factory.member(group)
    cds = await factory.cds_session(group, executive, starts_in=timedelta(minutes=-45), late_after_minutes=30)
    ex = await make_client()
    await ex.login(executive.email)
    payload = (await ex.post(f"/api/v1/sessions/{cds.id}/challenges")).json()["payload"]  # auto-starts first
    mc = await make_client()
    await mc.login(member.email)
    res = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert res.status_code == 201 and res.json()["status"] == "late"
