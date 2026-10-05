"""notifications

Revision ID: 0015_notifications
Revises: 0014_quotas
Create Date: 2026-10-05 06:39:12.468610
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_notifications"
down_revision: str | None = "0014_quotas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.String())), [{"id": "RECEIVE_ADMIN_ALERTS"}]
    )
    op.create_table(
        "notification_sources",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("kind", "source_id"),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("admin_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "source_id", "user_id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel IN ('EMAIL','TELEGRAM')"),
        sa.CheckConstraint("status IN ('PENDING','SENT','SUPPRESSED')"),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "channel"),
    )
    op.create_index(
        op.f("ix_notification_deliveries_next_attempt_at"),
        "notification_deliveries",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE id = 'RECEIVE_ADMIN_ALERTS'")
    op.drop_index(
        op.f("ix_notification_deliveries_next_attempt_at"), table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_table("notification_sources")
