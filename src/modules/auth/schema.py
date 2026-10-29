import re
import uuid
from typing import Optional

from pydantic import EmailStr, Field, field_validator

from src.core.config import Config
from src.shared.schemas import ApiModel

_STATE_CODE_RE = re.compile(Config.STATE_CODE_PATTERN)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_state_code(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def check_password_strength(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters.")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters.")
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        raise ValueError("Password must contain letters and numbers.")
    return value


class RegisterRequest(ApiModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str
    state_code: str
    group_id: uuid.UUID
    phone: Optional[str] = Field(default=None, max_length=32)
    consent: bool

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Enter your full name.")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("state_code")
    @classmethod
    def _state_code(cls, v: str) -> str:
        v = normalize_state_code(v)
        if not _STATE_CODE_RE.match(v):
            raise ValueError("Enter a valid state code, e.g. LA/24A/1234.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password_strength(v)

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must agree to the data-processing terms to register.")
        return v


class LoginRequest(ApiModel):
    """`identifier` accepts an email address or an NYSC state code."""

    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CsrfResponse(ApiModel):
    csrf_token: str
