"""In-app notifications: fan-out on session start (manual and automatic) and the inbox."""
from datetime import timedelta

from src.models.enums import MembershipRole, SessionStatus


async def _group(factory):
    area = await factory.area()
    group = await factory.group(area)
    executive = await factory.member(group, role=MembershipRole.executive)
    member = await factory.member(group)
    return group, executive, member


async def test_session_start_notifies_members(make_client, factory):
    group, executive, member = await _group(factory)
    cds = await factory.cds_session(group, executive, status=SessionStatus.scheduled)
    ex = await make_client()
    await ex.login(executive.email)
    mc = await make_client()
    await mc.login(member.email)

    await ex.post(f"/api/v1/sessions/{cds.id}/start")

    assert (await mc.get("/api/v1/notifications/unread-count")).json()["count"] == 1
    items = (await mc.get("/api/v1/notifications")).json()["items"]
    assert items[0]["type"] == "session_started"
    assert items[0]["entityId"] == str(cds.id)
    assert items[0]["readAt"] is None

    assert (await mc.post("/api/v1/notifications/mark-read")).json()["count"] == 0
    assert (await mc.get("/api/v1/notifications/unread-count")).json()["count"] == 0
    # Marking read is idempotent and doesn't remove the item from the inbox.
    assert len((await mc.get("/api/v1/notifications")).json()["items"]) == 1


async def test_auto_start_notifies_members(make_client, factory):
    group, executive, member = await _group(factory)
    # Due now but still 'scheduled' -> reading it auto-starts the session and fans out.
    cds = await factory.cds_session(group, executive, status=SessionStatus.scheduled,
                                    starts_in=timedelta(minutes=-5))
    mc = await make_client()
    await mc.login(member.email)

    assert (await mc.get(f"/api/v1/sessions/{cds.id}")).json()["status"] == "active"
    assert (await mc.get("/api/v1/notifications/unread-count")).json()["count"] == 1


async def test_notifications_are_per_recipient(make_client, factory):
    group, executive, _ = await _group(factory)
    outsider_group = await factory.group(await factory.area())
    outsider = await factory.member(outsider_group)
    cds = await factory.cds_session(group, executive, status=SessionStatus.scheduled)
    ex = await make_client()
    await ex.login(executive.email)
    oc = await make_client()
    await oc.login(outsider.email)

    await ex.post(f"/api/v1/sessions/{cds.id}/start")

    # A member of a different group is never notified about this session.
    assert (await oc.get("/api/v1/notifications/unread-count")).json()["count"] == 0
