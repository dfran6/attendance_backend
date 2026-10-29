"""Backwards-compatible import location. New code should import from src.core.permissions."""
from src.core.permissions import (  # noqa: F401
    Principal,
    get_current_user,
    get_principal,
    require_admin,
    require_approved,
)
