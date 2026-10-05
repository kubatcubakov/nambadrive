"""Quarantined document versions and durable pending scan queue."""

import sqlalchemy as sa

from alembic import op

revision = "0006_upload"
down_revision = "0005_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('PENDING','CLEAN','INFECTED','REJECTED')"),
        sa.CheckConstraint("size >= 0"),
        sa.CheckConstraint("length(sha256) = 64"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_versions")
