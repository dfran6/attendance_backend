"""session invariants

- At most one active session per CDS group (partial unique index).
- A session's scheduled end must be after its start (CHECK constraint).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_ONLY = "status = 'active'"


def upgrade() -> None:
    op.create_index(
        "uq_cds_sessions_one_active_per_group",
        "cds_sessions",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_ONLY),
        sqlite_where=sa.text(ACTIVE_ONLY),
    )
    with op.batch_alter_table("cds_sessions") as batch:
        batch.create_check_constraint(op.f("ck_cds_sessions_scheduled_window"), "scheduled_end > scheduled_start")


def downgrade() -> None:
    with op.batch_alter_table("cds_sessions") as batch:
        batch.drop_constraint(op.f("ck_cds_sessions_scheduled_window"), type_="check")
    op.drop_index("uq_cds_sessions_one_active_per_group", table_name="cds_sessions")
