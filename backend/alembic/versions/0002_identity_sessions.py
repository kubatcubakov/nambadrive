"""identity and application sessions

Revision ID: 0002_identity_sessions
Revises: 0001_bootstrap
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_identity_sessions"
down_revision: str | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("authentik_sub", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_authentik_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authentik_sub"),
    )
    op.create_index("ix_users_authentik_sub", "users", ["authentik_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=False)

    op.create_table(
        "application_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_hash"),
    )
    op.create_index(
        "ix_application_sessions_expires_at", "application_sessions", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_application_sessions_revoked_at", "application_sessions", ["revoked_at"], unique=False
    )
    op.create_index(
        "ix_application_sessions_session_hash",
        "application_sessions",
        ["session_hash"],
        unique=True,
    )
    op.create_index(
        "ix_application_sessions_user_id", "application_sessions", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_application_sessions_user_id", table_name="application_sessions")
    op.drop_index("ix_application_sessions_session_hash", table_name="application_sessions")
    op.drop_index("ix_application_sessions_revoked_at", table_name="application_sessions")
    op.drop_index("ix_application_sessions_expires_at", table_name="application_sessions")
    op.drop_table("application_sessions")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_authentik_sub", table_name="users")
    op.drop_table("users")
