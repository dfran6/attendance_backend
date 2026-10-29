from sqlmodel import select

from src.models import AuditLog, AuthSession, Membership, User
from src.modules.auth import service as auth_service_module
from tests.conftest import PASSWORD


def registration(group_id, **overrides):
    body = {
        "fullName": "  Ada   Okafor ",
        "email": "Ada.Okafor@Example.com",
        "password": PASSWORD,
        "stateCode": "la/24a/1234",
        "groupId": str(group_id),
        "consent": True,
    }
    body.update(overrides)
    return body


async def test_register_creates_pending_account_and_membership(client, factory, db):
    group = await factory.group(await factory.area())
    res = await client.post("/api/v1/auth/register", json=registration(group.id))

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["accountStatus"] == "pending"
    assert body["fullName"] == "Ada Okafor"
    assert body["email"] == "ada.okafor@example.com"
    assert body["stateCode"] == "LA/24A/1234"
    assert body["membership"]["status"] == "pending"
    assert body["membership"]["role"] == "member"
    assert body["roles"] == []
    assert "cds_access" in res.cookies and "cds_refresh" in res.cookies

    user = (await db.exec(select(User))).one()
    assert user.password_hash.startswith("$argon2id$")
    actions = (await db.exec(select(AuditLog.action))).all()
    assert "auth.registered" in actions


async def test_register_cannot_self_assign_privileges(client, factory, db):
    group = await factory.group(await factory.area())
    res = await client.post(
        "/api/v1/auth/register",
        json=registration(group.id, role="executive", accountStatus="approved", roles=["lgi"]),
    )
    assert res.status_code == 201
    assert res.json()["accountStatus"] == "pending"
    assert (await db.exec(select(Membership.role))).one() == "member"


async def test_register_rejects_duplicates(client, factory):
    group = await factory.group(await factory.area())
    await factory.user(email="taken@example.com", state_code="LA/24A/9999")

    res = await client.post("/api/v1/auth/register", json=registration(group.id, email="TAKEN@example.com"))
    assert res.status_code == 409
    assert res.json()["errorCode"] == "EMAIL_TAKEN"

    res = await client.post("/api/v1/auth/register", json=registration(group.id, stateCode="LA/24A/9999"))
    assert res.status_code == 409
    assert res.json()["errorCode"] == "STATE_CODE_TAKEN"


async def test_register_validation_errors_are_per_field(client, factory):
    group = await factory.group(await factory.area())
    res = await client.post(
        "/api/v1/auth/register",
        json=registration(group.id, stateCode="NOT-A-CODE", password="short", consent=False, email="nope"),
    )
    assert res.status_code == 422
    body = res.json()
    assert body["errorCode"] == "VALIDATION_ERROR"
    assert set(body["details"]["fields"]) >= {"stateCode", "password", "consent", "email"}


async def test_register_requires_active_group(client, factory):
    group = await factory.group(await factory.area(), active=False)
    res = await client.post("/api/v1/auth/register", json=registration(group.id))
    assert res.status_code == 422
    assert "groupId" in res.json()["details"]["fields"]


async def test_login_errors_do_not_reveal_account_existence(client, factory):
    await factory.user(email="real@example.com")
    wrong_password = await client.login("real@example.com", "WrongPassword1")
    unknown_user = await client.login("ghost@example.com", "WrongPassword1")
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["errorCode"] == "INVALID_CREDENTIALS"


async def test_login_with_email_or_state_code(client, factory):
    user = await factory.user(email="kemi@example.com", state_code="LA/24B/2222")
    assert (await client.login("KEMI@example.com")).status_code == 200
    res = await client.login("la/24b/2222")
    assert res.status_code == 200
    assert res.json()["id"] == str(user.id)


async def test_suspended_user_cannot_log_in(client, factory):
    from src.models.enums import AccountStatus

    await factory.user(email="sus@example.com", status=AccountStatus.suspended)
    res = await client.login("sus@example.com")
    assert res.status_code == 403
    assert res.json()["errorCode"] == "ACCOUNT_SUSPENDED"


async def test_me_requires_authentication(client):
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401
    assert res.json()["errorCode"] == "UNAUTHORIZED"


async def test_pending_user_is_blocked_from_operational_endpoints(client, factory):
    group = await factory.group(await factory.area())
    await client.post("/api/v1/auth/register", json=registration(group.id))
    assert (await client.get("/api/v1/users/me")).status_code == 200
    res = await client.get("/api/v1/groups")
    assert res.status_code == 403
    assert res.json()["errorCode"] == "ACCOUNT_PENDING"


async def test_unsafe_requests_require_csrf_token(make_client, factory):
    await factory.user(email="a@example.com")
    c = await make_client()
    res = await c.post("/api/v1/auth/login", json={"identifier": "a@example.com", "password": PASSWORD})
    assert res.status_code == 403
    assert res.json()["errorCode"] == "CSRF_FAILED"

    await c.prime_csrf()
    c.headers["X-CSRF-Token"] = "forged"
    res = await c.post("/api/v1/auth/login", json={"identifier": "a@example.com", "password": PASSWORD})
    assert res.json()["errorCode"] == "CSRF_FAILED"


async def test_refresh_rotates_tokens(client, factory, db):
    await factory.user(email="r@example.com")
    await client.login("r@example.com")
    first = client.cookies.get("cds_refresh")

    res = await client.post("/api/v1/auth/refresh")
    assert res.status_code == 200
    second = client.cookies.get("cds_refresh")
    assert second and second != first
    assert (await client.get("/api/v1/users/me")).status_code == 200

    sessions = (await db.exec(select(AuthSession))).all()
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s.revoked_at is None) == 1


async def test_refresh_token_reuse_revokes_the_whole_family(client, factory, db, monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr(auth_service_module, "REFRESH_REUSE_GRACE", timedelta(seconds=0))
    await factory.user(email="theft@example.com")
    await client.login("theft@example.com")
    stolen = client.cookies.get("cds_refresh")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200

    # Attacker replays the old token.
    replay = await client.post("/api/v1/auth/refresh", cookies={"cds_refresh": stolen})
    assert replay.status_code == 401

    assert all(s.revoked_at is not None for s in (await db.exec(select(AuthSession))).all())
    assert "auth.refresh_reuse_detected" in (await db.exec(select(AuditLog.action))).all()


async def test_concurrent_refresh_within_grace_does_not_log_user_out(client, factory, db):
    await factory.user(email="tabs@example.com")
    await client.login("tabs@example.com")
    old = client.cookies.get("cds_refresh")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    # Second tab raced with the old cookie: refused, but the new session survives.
    assert (await client.post("/api/v1/auth/refresh", cookies={"cds_refresh": old})).status_code == 401
    assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_logout_revokes_access_immediately(client, factory):
    await factory.user(email="out@example.com")
    await client.login("out@example.com")
    access = client.cookies.get("cds_access")

    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    # Even a still-unexpired access token stops working once its session is revoked.
    res = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert res.status_code == 401
    assert res.json()["errorCode"] == "SESSION_EXPIRED"


async def test_login_is_rate_limited(client, factory):
    await factory.user(email="rl@example.com")
    codes = [(await client.login("rl@example.com", "WrongPassword1")).status_code for _ in range(11)]
    assert codes[-1] == 429


async def test_update_me_only_changes_permitted_fields(client, factory):
    await factory.user(email="me@example.com")
    await client.login("me@example.com")
    res = await client.patch("/api/v1/users/me",
                             json={"fullName": "New  Name", "phone": "0801", "email": "evil@example.com"})
    assert res.status_code == 200
    assert res.json()["fullName"] == "New Name"
    assert res.json()["email"] == "me@example.com"
