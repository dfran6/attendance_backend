"""cds core schema

Replaces the initial prototype schema (34546e681727) with the CDS Attend data model:
admin areas, scoped roles, membership workflow, refresh sessions, CDS session lifecycle,
QR challenges, attendance with a (user, session) unique constraint, correction history,
excuses, audit logs and notifications.

SAFETY: the prototype tables are dropped, so upgrade() first verifies they are all EMPTY
and aborts otherwise. The prototype models could not insert rows (their UUID default was
not callable), so a real deployment should pass this check. Review before applying.

Revision ID: 0002
Revises: 34546e681727
Create Date: 2026-10-29
"""
import importlib.util
import os
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import context, op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "34546e681727"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TABLES = [
    "checkin_attempts", "attendance_corrections", "excuses", "attendance", "reports",
    "registration_links", "moderator_assignments", "memberships", "audit_events", "sessions",
    "groups", "users",
]
LEGACY_PG_ENUMS = ["user_role_enum", "user_status_enum"]


def _assert_legacy_tables_empty() -> None:
    if context.is_offline_mode():
        return  # --sql output is reviewed by a human; the check runs on real upgrades.
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    non_empty = [
        t for t in LEGACY_TABLES
        if t in existing and bind.execute(sa.text(f'SELECT 1 FROM "{t}" LIMIT 1')).first() is not None
    ]
    if non_empty:
        raise RuntimeError(
            "Refusing to drop non-empty legacy tables: " + ", ".join(non_empty)
            + ". Export or migrate that data first."
        )


def upgrade() -> None:
    _assert_legacy_tables_empty()
    for table in LEGACY_TABLES:
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        for enum_name in LEGACY_PG_ENUMS:
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    op.create_table('admin_areas',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_areas')),
    sa.UniqueConstraint('code', name=op.f('uq_admin_areas_code'))
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('state_code', sa.String(length=32), nullable=False),
    sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('account_status', sa.Enum('pending', 'approved', 'rejected', 'suspended', name='account_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_account_status'), 'users', ['account_status'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_state_code'), 'users', ['state_code'], unique=True)
    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('target_type', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('target_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('area_id', sa.Uuid(), nullable=True),
    sa.Column('group_id', sa.Uuid(), nullable=True),
    sa.Column('request_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('ip_address', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('context', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'], unique=False)
    op.create_index('ix_audit_logs_area_created', 'audit_logs', ['area_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_group_created', 'audit_logs', ['group_id', 'created_at'], unique=False)
    op.create_table('auth_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_id', sa.Uuid(), nullable=True),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('ip_address', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_sessions_token_hash'))
    )
    op.create_index(op.f('ix_auth_sessions_family_id'), 'auth_sessions', ['family_id'], unique=False)
    op.create_index('ix_auth_sessions_user_active', 'auth_sessions', ['user_id', 'revoked_at'], unique=False)
    op.create_table('cds_groups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('area_id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['admin_areas.id'], name=op.f('fk_cds_groups_area_id_admin_areas')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cds_groups')),
    sa.UniqueConstraint('area_id', 'name', name='uq_cds_groups_area_name'),
    sa.UniqueConstraint('code', name=op.f('uq_cds_groups_code'))
    )
    op.create_index(op.f('ix_cds_groups_area_id'), 'cds_groups', ['area_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('recipient_id', sa.Uuid(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('entity_type', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('entity_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=160), nullable=False),
    sa.Column('body', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], name=op.f('fk_notifications_recipient_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('ix_notifications_recipient_read', 'notifications', ['recipient_id', 'read_at'], unique=False)
    op.create_table('role_assignments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('lgi', 'super_admin', name='admin_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('area_id', sa.Uuid(), nullable=True),
    sa.Column('granted_by_id', sa.Uuid(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['area_id'], ['admin_areas.id'], name=op.f('fk_role_assignments_area_id_admin_areas')),
    sa.ForeignKeyConstraint(['granted_by_id'], ['users.id'], name=op.f('fk_role_assignments_granted_by_id_users')),
    sa.ForeignKeyConstraint(['revoked_by_id'], ['users.id'], name=op.f('fk_role_assignments_revoked_by_id_users')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_role_assignments_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_assignments'))
    )
    op.create_index(op.f('ix_role_assignments_area_id'), 'role_assignments', ['area_id'], unique=False)
    op.create_index(op.f('ix_role_assignments_user_id'), 'role_assignments', ['user_id'], unique=False)
    op.create_index('uq_role_assignments_active', 'role_assignments', ['user_id', 'role', 'area_id'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'), sqlite_where=sa.text('revoked_at IS NULL'))
    op.create_table('cds_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=160), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
    sa.Column('venue', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
    sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actual_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actual_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('late_after_minutes', sa.Integer(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('radius_m', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('scheduled', 'active', 'closed', 'archived', 'cancelled', name='session_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_cds_sessions_created_by_id_users')),
    sa.ForeignKeyConstraint(['group_id'], ['cds_groups.id'], name=op.f('fk_cds_sessions_group_id_cds_groups')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cds_sessions'))
    )
    op.create_index('ix_cds_sessions_group_start', 'cds_sessions', ['group_id', 'scheduled_start'], unique=False)
    op.create_index(op.f('ix_cds_sessions_status'), 'cds_sessions', ['status'], unique=False)
    op.create_table('memberships',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('member', 'executive', name='membership_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'revoked', name='membership_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('decided_by_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=op.f('fk_memberships_decided_by_id_users')),
    sa.ForeignKeyConstraint(['group_id'], ['cds_groups.id'], name=op.f('fk_memberships_group_id_cds_groups')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships'))
    )
    op.create_index('ix_memberships_group_status', 'memberships', ['group_id', 'status'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_index('uq_memberships_one_active_per_user', 'memberships', ['user_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'approved')"), sqlite_where=sa.text("status IN ('pending', 'approved')"))
    op.create_table('excuses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('category', sa.Enum('medical', 'official_duty', 'emergency', 'other', name='excuse_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('explanation', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False),
    sa.Column('evidence_key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('evidence_content_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('status', sa.Enum('submitted', 'under_review', 'approved', 'rejected', 'withdrawn', name='excuse_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_by_id', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['cds_groups.id'], name=op.f('fk_excuses_group_id_cds_groups')),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], name=op.f('fk_excuses_reviewed_by_id_users')),
    sa.ForeignKeyConstraint(['session_id'], ['cds_sessions.id'], name=op.f('fk_excuses_session_id_cds_sessions')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_excuses_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_excuses'))
    )
    op.create_index('ix_excuses_group_status', 'excuses', ['group_id', 'status'], unique=False)
    op.create_index(op.f('ix_excuses_user_id'), 'excuses', ['user_id'], unique=False)
    op.create_table('qr_challenges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('issued_by_id', sa.Uuid(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['issued_by_id'], ['users.id'], name=op.f('fk_qr_challenges_issued_by_id_users')),
    sa.ForeignKeyConstraint(['session_id'], ['cds_sessions.id'], name=op.f('fk_qr_challenges_session_id_cds_sessions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qr_challenges'))
    )
    op.create_index(op.f('ix_qr_challenges_session_id'), 'qr_challenges', ['session_id'], unique=False)
    op.create_table('attendance_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('present', 'late', 'absent', 'excused', name='attendance_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('method', sa.Enum('qr', 'manual', name='verification_method', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('challenge_id', sa.Uuid(), nullable=True),
    sa.Column('recorded_by_id', sa.Uuid(), nullable=True),
    sa.Column('distance_m', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['challenge_id'], ['qr_challenges.id'], name=op.f('fk_attendance_records_challenge_id_qr_challenges')),
    sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], name=op.f('fk_attendance_records_recorded_by_id_users')),
    sa.ForeignKeyConstraint(['session_id'], ['cds_sessions.id'], name=op.f('fk_attendance_records_session_id_cds_sessions')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_attendance_records_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_records')),
    sa.UniqueConstraint('user_id', 'session_id', name='uq_attendance_user_session')
    )
    op.create_index(op.f('ix_attendance_records_user_id'), 'attendance_records', ['user_id'], unique=False)
    op.create_index('ix_attendance_session_status', 'attendance_records', ['session_id', 'status'], unique=False)
    op.create_table('attendance_corrections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('attendance_id', sa.Uuid(), nullable=False),
    sa.Column('changed_by_id', sa.Uuid(), nullable=False),
    sa.Column('previous_status', sa.Enum('present', 'late', 'absent', 'excused', name='previous_attendance_status', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('new_status', sa.Enum('present', 'late', 'absent', 'excused', name='attendance_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attendance_id'], ['attendance_records.id'], name=op.f('fk_attendance_corrections_attendance_id_attendance_records')),
    sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], name=op.f('fk_attendance_corrections_changed_by_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_corrections'))
    )
    op.create_index(op.f('ix_attendance_corrections_attendance_id'), 'attendance_corrections', ['attendance_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_attendance_corrections_attendance_id'), table_name='attendance_corrections')
    op.drop_table('attendance_corrections')
    op.drop_index('ix_attendance_session_status', table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_user_id'), table_name='attendance_records')
    op.drop_table('attendance_records')
    op.drop_index(op.f('ix_qr_challenges_session_id'), table_name='qr_challenges')
    op.drop_table('qr_challenges')
    op.drop_index(op.f('ix_excuses_user_id'), table_name='excuses')
    op.drop_index('ix_excuses_group_status', table_name='excuses')
    op.drop_table('excuses')
    op.drop_index('uq_memberships_one_active_per_user', table_name='memberships', postgresql_where=sa.text("status IN ('pending', 'approved')"), sqlite_where=sa.text("status IN ('pending', 'approved')"))
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index('ix_memberships_group_status', table_name='memberships')
    op.drop_table('memberships')
    op.drop_index(op.f('ix_cds_sessions_status'), table_name='cds_sessions')
    op.drop_index('ix_cds_sessions_group_start', table_name='cds_sessions')
    op.drop_table('cds_sessions')
    op.drop_index('uq_role_assignments_active', table_name='role_assignments', postgresql_where=sa.text('revoked_at IS NULL'), sqlite_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_role_assignments_user_id'), table_name='role_assignments')
    op.drop_index(op.f('ix_role_assignments_area_id'), table_name='role_assignments')
    op.drop_table('role_assignments')
    op.drop_index('ix_notifications_recipient_read', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_cds_groups_area_id'), table_name='cds_groups')
    op.drop_table('cds_groups')
    op.drop_index('ix_auth_sessions_user_active', table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_family_id'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index('ix_audit_logs_group_created', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_area_created', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_state_code'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_account_status'), table_name='users')
    op.drop_table('users')
    op.drop_table('admin_areas')

    # Recreate the prototype schema exactly as revision 34546e681727 defined it.
    path = os.path.join(os.path.dirname(__file__), "34546e681727_init.py")
    spec = importlib.util.spec_from_file_location("_init_revision", path)
    init = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init)
    init.upgrade()
