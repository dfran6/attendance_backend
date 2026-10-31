"""allow the 'location' verification method

Widen the attendance_records.method CHECK constraint so GPS self check-ins
(no QR scan) can be recorded alongside 'qr' and 'manual'.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = op.f("ck_attendance_records_verification_method")
OLD = "method IN ('qr', 'manual')"
NEW = "method IN ('qr', 'manual', 'location')"


def upgrade() -> None:
    with op.batch_alter_table("attendance_records") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, NEW)


def downgrade() -> None:
    with op.batch_alter_table("attendance_records") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, OLD)
