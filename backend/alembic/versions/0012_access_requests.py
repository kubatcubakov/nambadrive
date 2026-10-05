"""Audited owner/manager access requests and temporary grants."""

import sqlalchemy as sa

from alembic import op

revision = "0012_access_requests"
down_revision = "0011_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission_id", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("requested_until", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.String(2000)),
        sa.Column("acl_entry_id", sa.Uuid(), sa.ForeignKey("acl_entries.id")),
        sa.CheckConstraint("permission_id IN ('VIEW','EDIT','DOWNLOAD')"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','DENIED')"),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL) OR "
            "(status != 'PENDING' AND decided_at IS NOT NULL AND decided_by IS NOT NULL)"
        ),
    )
    op.create_index("ix_access_requests_resource_id", "access_requests", ["resource_id"])
    op.create_index("ix_access_requests_requested_by", "access_requests", ["requested_by"])
    op.create_index(
        "uq_pending_access_request",
        "access_requests",
        ["resource_id", "requested_by", "permission_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_table("access_requests")
