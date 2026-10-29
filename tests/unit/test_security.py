import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.core.config import Config
from src.core.security import (
    TokenExpired,
    TokenInvalid,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_argon2id_round_trip():
    h = hash_password("Correct horse 1")
    assert h.startswith("$argon2id$")
    assert verify_password("Correct horse 1", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_access_token_expiry_is_utc_based():
    token = create_access_token(uuid.uuid4(), uuid.uuid4())
    claims = jwt.decode(token, Config.JWT_SECRET, algorithms=[Config.JWT_ALGORITHM])
    remaining = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert 0 < remaining <= Config.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_expired_and_tampered_tokens_are_rejected():
    expired = jwt.encode(
        {"sub": "x", "sid": "y", "type": "access", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        Config.JWT_SECRET, algorithm=Config.JWT_ALGORITHM,
    )
    with pytest.raises(TokenExpired):
        decode_access_token(expired)
    with pytest.raises(TokenInvalid):
        decode_access_token(create_access_token(uuid.uuid4(), uuid.uuid4()) + "x")
    unsigned = jwt.encode({"sub": "x", "type": "access", "exp": 9999999999}, "other-key", algorithm="HS256")
    with pytest.raises(TokenInvalid):
        decode_access_token(unsigned)
