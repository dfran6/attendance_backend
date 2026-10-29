# CDS Attend — API

FastAPI backend for NYSC Community Development Service attendance. The web client lives in
`../attendance_frontend`.

## Status

| Phase | Area | State |
|---|---|---|
| 1 | Repo audit, config validation, error envelope, logging, health/readiness | **Done** |
| 2 | Registration, login (email or state code), rotating refresh sessions, logout, CSRF, `/users/me` | **Done, tested** |
| 3 | Admin areas, groups, membership approval/rejection/re-apply, LGI role assignment | **Done, tested** |
| 4 | Session lifecycle, signed QR challenges, check-in (geofence optional), manual attendance with correction history | **Done, tested** |
| 5 | Excuses and private documents | Models + migration only |
| 6–7 | Reports, audit-log UI, moderators, Docker, CI | Planned |

## Run locally

Requires Python 3.9+ (3.12 recommended) and PostgreSQL. Redis is optional locally.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set DATABASE_URL and JWT_SECRET
alembic upgrade head          # controlled step — never run automatically by the app
python -m src.scripts.bootstrap --email you@example.com --name "Your Name" \
  --state-code LA/24A/0001 --area-name Ikeja --area-code IKJ --state Lagos \
  --group-name "Health" --group-code IKJ-HEALTH      # first super admin (prompts for password)
uvicorn src.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs (disabled when `APP_ENV=production`).

## Tests

```bash
pytest -q
```

Tests run against an isolated, throwaway SQLite database with synthetic data. They never touch
`DATABASE_URL` from `.env`.

## Architecture

Modular monolith: `src/modules/<domain>/{routes,schema,service}.py`, with all table models in
`src/models/` (one import point for Alembic, no circular imports).

- **Authorization** (`src/core/permissions.py`): every protected route resolves a `Principal`.
  Roles are *scoped and derived*, never self-assigned:
  - *member / executive* → the user's single approved `Membership` (role on that group)
  - *lgi* → `RoleAssignment` tied to an `AdminArea`; *super_admin* → unscoped `RoleAssignment`
  Services call `ensure_can_manage_group(group)` / `ensure_can_oversee_area(area_id)` with the
  concrete resource. Out-of-scope membership IDs return 404 (no ID probing).
- **Sessions**: 15-min access JWT + opaque 7-day refresh token (stored as SHA-256), both in
  HttpOnly cookies. Refresh rotates; replaying a rotated token revokes the whole family
  (15-second grace for concurrent tabs). Access tokens are bound to their session, so logout
  takes effect immediately.
- **CSRF**: double-submit token (`GET /api/v1/auth/csrf` → `X-CSRF-Token` header) on all unsafe
  `/api/*` requests that use cookies. Bearer-header clients are exempt.
- **Errors**: `{statusCode, message, errorCode, details}`; codes in `src/core/exceptions.py`.
  Validation errors carry `details.fields` keyed by camelCase field name.
- **Audit**: `audit.record(...)` writes in the same transaction as the action it describes.
- **Enums** are VARCHAR + CHECK constraints (easy to extend); constraint names follow a
  deterministic naming convention (`src/models/base.py`).

### Account lifecycle

```
register → account pending + membership pending
executive/LGI approves → membership approved, account approved
executive/LGI rejects (reason required) → membership rejected, account rejected
rejected user re-applies to a group → new pending membership, account pending
suspended (admin) → cannot log in or refresh
```

## Product decisions

- **Account approval:** a group executive *or* the area LGI may approve a membership request;
  approving the first membership also approves the account.
- **Attendance rate (phase 6 reports):** approved excuses are **their own category**, not removed
  from the denominator. Each session's eligible members are counted as exactly one of
  `present`, `late`, `excused`, `absent`, so:
  - `attendance rate = (present + late) / eligible members`
  - `excused` and `absent` are reported alongside as separate shares.

## Sessions & attendance (phase 4)

```
scheduled → active (start: from 60 min before scheduled start until scheduled end)
scheduled → cancelled
active    → closed   (QR codes stop validating immediately)
closed    → archived (attendance becomes read-only)
```

- One active session per group (partial unique index). Closed sessions are not reopened;
  late fixes go through manual corrections.
- **QR challenge** (`POST /sessions/{id}/challenges`): `CDSA1.<jwt>` with a 20 s expiry,
  signed with a key derived from `JWT_SECRET` and a dedicated audience, so access tokens and QR
  codes are never interchangeable. Holds only opaque IDs. Expiry is judged on server time.
- **Check-in** (`POST /attendance/checkin`): approved member of the session's group, active
  session, valid unexpired code. Duplicates and concurrent retries are stopped by the
  `(user_id, session_id)` unique constraint and return `409 DUPLICATE_CHECKIN`. A check-in after
  `lateAfterMinutes` counts as `late`. Rate limits are per user, since venues share Wi-Fi.
- **Geofence** (optional per session): `428 LOCATION_REQUIRED` asks the client for coordinates.
  Distance is computed on the server, and only `distance_m` is stored, never coordinates. GPS is
  treated as supporting evidence, not proof of presence. Refused check-ins are audited.
- **Manual attendance** (`POST /sessions/{id}/attendance/manual`, `PATCH /attendance/{id}`):
  managers only, active or closed sessions, reason required, never on your own record. Every
  change appends an `attendance_corrections` row (from → to, who, why). History is at
  `GET /attendance/{id}/corrections`.
- **Absence is derived**, not stored: an approved member with no record on a non-active session.

## Migrations

`0002_cds_core_schema` replaces the prototype schema from `34546e681727`. It **aborts if any
prototype table contains rows**, so it cannot silently destroy data. It has been verified
against SQLite (upgrade, `alembic check`, downgrade, upgrade) and renders valid PostgreSQL
(`alembic upgrade head --sql`). Review that SQL before applying to a shared database.

## Configuration

See `.env.example`. Startup fails fast on an empty `DATABASE_URL`; in production it also
requires a ≥32-char `JWT_SECRET`, `COOKIE_SECURE=true` and `REDIS_URL`.
