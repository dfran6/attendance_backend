"""QR check-in security: signatures, expiry, replay, scope, geofence, concurrency."""
import asyncio
from datetime import timedelta

import jwt
from sqlmodel import select

from src.core.config import Config
from src.models import AttendanceRecord, AuditLog
from src.models.enums import AccountStatus, MembershipRole, MembershipStatus, SessionStatus

VENUE = (6.6018, 3.3515, 100)  # lat, lon, radius (m)


async def _setup(factory, make_client, **session_kw):
    area = await factory.area()
    group = await factory.group(area)
    executive = await factory.member(group, role=MembershipRole.executive)
    member = await factory.member(group)
    cds = await factory.cds_session(group, executive, status=SessionStatus.active, **session_kw)
    exec_client = await make_client()
    await exec_client.login(executive.email)
    member_client = await make_client()
    await member_client.login(member.email)
    return group, executive, member, cds, exec_client, member_client


async def _code(exec_client, cds) -> str:
    res = await exec_client.post(f"/api/v1/sessions/{cds.id}/challenges")
    assert res.status_code == 201, res.text
    return res.json()["payload"]


async def test_check_in_present_then_duplicate(make_client, factory, db):
    _, _, member, cds, ex, mc = await _setup(factory, make_client)
    payload = await _code(ex, cds)

    res = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "present" and res.json()["method"] == "qr"

    again = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert again.status_code == 409 and again.json()["errorCode"] == "DUPLICATE_CHECKIN"
    assert again.json()["details"]["status"] == "present"
    assert len((await db.exec(select(AttendanceRecord))).all()) == 1


async def test_late_check_in(make_client, factory):
    _, _, _, cds, ex, mc = await _setup(factory, make_client, started_ago=timedelta(minutes=45))
    res = await mc.post("/api/v1/attendance/checkin", json={"payload": await _code(ex, cds)})
    assert res.json()["status"] == "late"


async def test_expired_challenge(make_client, factory, monkeypatch):
    _, _, _, cds, ex, mc = await _setup(factory, make_client)
    monkeypatch.setattr(Config, "QR_CHALLENGE_TTL_SECONDS", -30)
    payload = await _code(ex, cds)
    res = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert res.status_code == 400 and res.json()["errorCode"] == "CHALLENGE_EXPIRED"


async def test_tampered_and_forged_codes(make_client, factory, db):
    _, _, _, cds, ex, mc = await _setup(factory, make_client)
    payload = await _code(ex, cds)
    head, body, sig = payload[len("CDSA1."):].split(".")

    tampered = "CDSA1." + ".".join([head, body, sig[:-2] + ("AA" if sig[-2:] != "AA" else "BB")])
    forged = "CDSA1." + jwt.encode({"jti": "x", "sid": str(cds.id), "exp": 9999999999, "aud": "cds-attend:qr-challenge"},
                                   Config.JWT_SECRET, algorithm="HS256")  # signed with the *access-token* key
    access_token = "CDSA1." + mc.cookies.get("cds_access")
    for bad in (tampered, forged, access_token, "not a code at all"):
        res = await mc.post("/api/v1/attendance/checkin", json={"payload": bad})
        assert res.status_code in (400, 422) and res.json()["errorCode"] in ("INVALID_CHALLENGE", "VALIDATION_ERROR"), bad
    assert (await db.exec(select(AttendanceRecord))).all() == []
    assert "attendance.checkin_rejected" in (await db.exec(select(AuditLog.action))).all()


async def test_code_stops_working_when_session_closes(make_client, factory):
    _, _, _, cds, ex, mc = await _setup(factory, make_client)
    payload = await _code(ex, cds)
    await ex.post(f"/api/v1/sessions/{cds.id}/close")
    res = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert res.status_code == 409 and res.json()["errorCode"] == "SESSION_NOT_ACTIVE"


async def test_member_of_another_group_cannot_use_code(make_client, factory):
    group, _, _, cds, ex, _ = await _setup(factory, make_client)
    outsider_group = await factory.group(await factory.area())
    outsider = await factory.member(outsider_group)
    c = await make_client()
    await c.login(outsider.email)
    res = await c.post("/api/v1/attendance/checkin", json={"payload": await _code(ex, cds)})
    assert res.status_code == 403


async def test_pending_member_cannot_check_in(make_client, factory):
    group, _, _, cds, ex, _ = await _setup(factory, make_client)
    pending = await factory.member(group, status=MembershipStatus.pending)
    assert pending.account_status == AccountStatus.pending
    c = await make_client()
    await c.login(pending.email)
    res = await c.post("/api/v1/attendance/checkin", json={"payload": await _code(ex, cds)})
    assert res.status_code == 403 and res.json()["errorCode"] == "ACCOUNT_PENDING"


async def test_geofence(make_client, factory, db):
    _, _, _, cds, ex, mc = await _setup(factory, make_client, geofence=VENUE)
    payload = await _code(ex, cds)

    res = await mc.post("/api/v1/attendance/checkin", json={"payload": payload})
    assert res.status_code == 428 and res.json()["errorCode"] == "LOCATION_REQUIRED"

    far = await mc.post("/api/v1/attendance/checkin", json={"payload": payload, "latitude": 6.62, "longitude": 3.35})
    assert far.status_code == 403 and far.json()["errorCode"] == "OUT_OF_BOUNDS"
    assert far.json()["details"]["distanceM"] > 1000

    near = await mc.post("/api/v1/attendance/checkin",
                         json={"payload": payload, "latitude": 6.6022, "longitude": 3.3517, "accuracyM": 15})
    assert near.status_code == 201, near.text
    assert 0 < near.json()["distanceM"] <= 100
    # Only the distance is retained, never raw coordinates.
    assert not hasattr(AttendanceRecord, "latitude")


async def test_concurrent_check_ins_produce_one_record(make_client, factory, db):
    _, _, _, cds, ex, mc = await _setup(factory, make_client)
    payload = await _code(ex, cds)
    results = await asyncio.gather(
        *[mc.post("/api/v1/attendance/checkin", json={"payload": payload}) for _ in range(4)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and all(c == 409 for c in codes if c != 201), codes
    assert len((await db.exec(select(AttendanceRecord))).all()) == 1
