from enum import Enum


class AccountStatus(str, Enum):
    """pending -> approved | rejected; approved <-> suspended; rejected -> pending (re-apply)."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class MembershipRole(str, Enum):
    member = "member"
    executive = "executive"


class MembershipStatus(str, Enum):
    """pending -> approved | rejected; approved -> revoked."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    revoked = "revoked"


class AdminRole(str, Enum):
    lgi = "lgi"
    super_admin = "super_admin"


class SessionStatus(str, Enum):
    """scheduled -> active | cancelled; active -> closed; closed -> archived."""

    scheduled = "scheduled"
    active = "active"
    closed = "closed"
    archived = "archived"
    cancelled = "cancelled"


class AttendanceStatus(str, Enum):
    present = "present"
    late = "late"
    absent = "absent"
    excused = "excused"


class VerificationMethod(str, Enum):
    qr = "qr"
    manual = "manual"
    location = "location"  # self check-in verified by GPS geofence, no QR scan


class ExcuseCategory(str, Enum):
    medical = "medical"
    official_duty = "official_duty"
    emergency = "emergency"
    other = "other"


class ExcuseStatus(str, Enum):
    """submitted -> under_review -> approved | rejected; submitted -> withdrawn."""

    submitted = "submitted"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"
