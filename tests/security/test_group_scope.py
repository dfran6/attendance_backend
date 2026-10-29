"""Cross-group and privilege-escalation checks for the membership workflow."""
from sqlmodel import select

from src.models import AuditLog, User
from src.models.enums import MembershipRole, MembershipStatus
from tests.conftest import membership_id_for


async def _setup(factory):
    area = await factory.area()
    group_a = await factory.group(area, "Health")
    group_b = await factory.group(area, "Education")
    exec_a = await factory.member(group_a, role=MembershipRole.executive)
    applicant_b = await factory.member(group_b, status=MembershipStatus.pending)
    applicant_a = await factory.member(group_a, status=MembershipStatus.pending)
    return area, group_a, group_b, exec_a, applicant_a, applicant_b


async def test_executive_approves_member_of_own_group(client, factory, db):
    _, group_a, _, exec_a, applicant_a, _ = await _setup(factory)
    await client.login(exec_a.email)

    listing = await client.get(f"/api/v1/groups/{group_a.id}/memberships", params={"status": "pending"})
    assert listing.status_code == 200
    assert [m["userId"] for m in listing.json()["items"]] == [str(applicant_a.id)]

    mid = await membership_id_for(db, applicant_a.id)
    res = await client.post(f"/api/v1/memberships/{mid}/approve")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
    assert res.json()["accountStatus"] == "approved"
    assert "membership.approved" in (await db.exec(select(AuditLog.action))).all()


async def test_decision_is_not_repeatable(client, factory, db):
    _, _, _, exec_a, applicant_a, _ = await _setup(factory)
    await client.login(exec_a.email)
    mid = await membership_id_for(db, applicant_a.id)
    assert (await client.post(f"/api/v1/memberships/{mid}/approve")).status_code == 200
    res = await client.post(f"/api/v1/memberships/{mid}/reject", json={"reason": "changed my mind"})
    assert res.status_code == 409
    assert res.json()["errorCode"] == "INVALID_TRANSITION"


async def test_executive_cannot_touch_another_group_by_changing_ids(client, factory, db):
    _, _, group_b, exec_a, _, applicant_b = await _setup(factory)
    await client.login(exec_a.email)

    assert (await client.get(f"/api/v1/groups/{group_b.id}/memberships")).status_code == 403
    assert (await client.get(f"/api/v1/groups/{group_b.id}")).status_code == 403
    mid = await membership_id_for(db, applicant_b.id)
    res = await client.post(f"/api/v1/memberships/{mid}/approve")
    assert res.status_code == 404
    assert (await db.get(User, applicant_b.id)).account_status == "pending"


async def test_ordinary_member_cannot_approve(client, factory, db):
    _, group_a, _, _, applicant_a, _ = await _setup(factory)
    member = await factory.member(group_a)
    await client.login(member.email)
    mid = await membership_id_for(db, applicant_a.id)
    assert (await client.post(f"/api/v1/memberships/{mid}/approve")).status_code == 404
    assert (await client.get(f"/api/v1/groups/{group_a.id}/memberships")).status_code == 403


async def test_executive_cannot_promote_members(client, factory, db):
    _, group_a, _, exec_a, _, _ = await _setup(factory)
    member = await factory.member(group_a)
    await client.login(exec_a.email)
    mid = await membership_id_for(db, member.id)
    res = await client.post(f"/api/v1/memberships/{mid}/role", json={"role": "executive"})
    assert res.status_code == 403


async def test_lgi_can_promote_within_area_only(make_client, factory, db):
    area = await factory.area()
    other_area = await factory.area("Surulere")
    group = await factory.group(area)
    foreign_group = await factory.group(other_area)
    member = await factory.member(group)
    foreign_member = await factory.member(foreign_group)
    lgi = await factory.lgi(area)

    c = await make_client()
    await c.login(lgi.email)
    res = await c.post(f"/api/v1/memberships/{await membership_id_for(db, member.id)}/role", json={"role": "executive"})
    assert res.status_code == 200
    assert res.json()["role"] == "executive"

    res = await c.post(f"/api/v1/memberships/{await membership_id_for(db, foreign_member.id)}/role",
                       json={"role": "executive"})
    assert res.status_code == 404
    groups = (await c.get("/api/v1/groups")).json()
    assert [g["id"] for g in groups] == [str(group.id)]


async def test_reject_requires_reason_and_rejects_pending_account(client, factory, db):
    _, _, _, exec_a, applicant_a, _ = await _setup(factory)
    await client.login(exec_a.email)
    mid = await membership_id_for(db, applicant_a.id)
    assert (await client.post(f"/api/v1/memberships/{mid}/reject", json={})).status_code == 422
    res = await client.post(f"/api/v1/memberships/{mid}/reject", json={"reason": "Not posted to this LGA"})
    assert res.status_code == 200
    assert res.json()["accountStatus"] == "rejected"


async def test_rejected_user_can_reapply(make_client, factory, db):
    area, group_a, group_b, exec_a, applicant_a, _ = await _setup(factory)
    executive = await make_client()
    await executive.login(exec_a.email)
    await executive.post(f"/api/v1/memberships/{await membership_id_for(db, applicant_a.id)}/reject",
                         json={"reason": "Wrong group"})

    applicant = await make_client()
    await applicant.login(applicant_a.email)
    res = await applicant.post("/api/v1/memberships", json={"groupId": str(group_b.id)})
    assert res.status_code == 201, res.text
    me = (await applicant.get("/api/v1/users/me")).json()
    assert me["accountStatus"] == "pending"
    assert me["membership"]["groupId"] == str(group_b.id)

    # And cannot hold two open requests at once.
    assert (await applicant.post("/api/v1/memberships", json={"groupId": str(group_a.id)})).status_code == 409


async def test_only_admins_create_groups_and_only_super_admin_creates_areas(make_client, factory):
    area = await factory.area()
    other_area = await factory.area()
    group = await factory.group(area)
    executive = await factory.member(group, role=MembershipRole.executive)
    lgi = await factory.lgi(area)
    root = await factory.super_admin()

    c = await make_client()
    await c.login(executive.email)
    body = {"areaId": str(area.id), "name": "Sports", "code": "spt-1"}
    assert (await c.post("/api/v1/groups", json=body)).status_code == 403

    c = await make_client()
    await c.login(lgi.email)
    created = await c.post("/api/v1/groups", json=body)
    assert created.status_code == 201 and created.json()["code"] == "SPT-1"
    assert (await c.post("/api/v1/groups", json={**body, "areaId": str(other_area.id), "code": "X2"})).status_code == 403
    assert (await c.post("/api/v1/areas", json={"name": "Yaba", "code": "YB", "state": "Lagos"})).status_code == 403

    c = await make_client()
    await c.login(root.email)
    assert (await c.post("/api/v1/areas", json={"name": "Yaba", "code": "YB", "state": "Lagos"})).status_code == 201


async def test_public_group_list_hides_inactive_groups(client, factory):
    area = await factory.area()
    active = await factory.group(area)
    await factory.group(area, active=False)
    res = await client.get("/api/v1/groups/public")
    assert res.status_code == 200
    assert [g["id"] for g in res.json()] == [str(active.id)]
