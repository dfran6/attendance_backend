"""Signed, short-lived QR attendance challenges.

The QR payload is `CDSA1.<jwt>`. The JWT is signed with a key *derived* from JWT_SECRET and
carries a dedicated audience, so an access token can never be accepted as a QR challenge (or the
reverse). It contains only opaque IDs and timestamps — no personal data or credentials.
"""
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Tuple

import jwt

from src.core.config import Config
from src.core.exceptions import AppError, ErrorCode

QR_PREFIX = "CDSA1."
QR_AUDIENCE = "cds-attend:qr-challenge"
# Tolerates scan-to-request latency only; expiry is always judged by server time.
VERIFY_LEEWAY_SECONDS = 2


def _signing_key() -> str:
    return hashlib.sha256(f"{Config.JWT_SECRET}:qr-challenge:v1".encode()).hexdigest()


def challenge_ttl() -> timedelta:
    return timedelta(seconds=Config.QR_CHALLENGE_TTL_SECONDS)


def sign_challenge(challenge_id: uuid.UUID, session_id: uuid.UUID, issued_at: datetime, expires_at: datetime) -> str:
    token = jwt.encode(
        {
            "jti": str(challenge_id),
            "sid": str(session_id),
            "iat": issued_at,
            "exp": expires_at,
            "aud": QR_AUDIENCE,
        },
        _signing_key(),
        algorithm="HS256",
    )
    return QR_PREFIX + token


def invalid_challenge() -> AppError:
    return AppError(400, ErrorCode.INVALID_CHALLENGE, "That code isn't a valid CDS Attend check-in code.")


def verify_challenge(payload: str) -> Tuple[uuid.UUID, uuid.UUID]:
    """Returns (challenge_id, session_id) or raises AppError."""
    payload = (payload or "").strip()
    if not payload.startswith(QR_PREFIX):
        raise invalid_challenge()
    try:
        claims = jwt.decode(
            payload[len(QR_PREFIX):],
            _signing_key(),
            algorithms=["HS256"],
            audience=QR_AUDIENCE,
            leeway=VERIFY_LEEWAY_SECONDS,
            options={"require": ["exp", "jti", "sid", "aud"]},
        )
        return uuid.UUID(claims["jti"]), uuid.UUID(claims["sid"])
    except jwt.ExpiredSignatureError:
        raise AppError(400, ErrorCode.CHALLENGE_EXPIRED, "That code has expired. Scan the code on screen again.")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise invalid_challenge()
