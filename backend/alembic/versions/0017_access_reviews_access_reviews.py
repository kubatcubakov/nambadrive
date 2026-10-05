"""access_reviews

Revision ID: 0017_access_reviews
Revises: 0015_notifications
Create Date: 2026-10-05 07:06:14.913968
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_access_reviews"
down_revision: str | None = "0015_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("quarter", sa.Date(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["completed_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "quarter"),
    )
    op.create_index(
        op.f("ix_access_reviews_resource_id"), "access_reviews", ["resource_id"], unique=False
    )
    op.create_table(
        "access_review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("decision IN ('PENDING','KEEP','REVOKE','SUPERSEDED')"),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["access_reviews.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "source_key", "fingerprint"),
    )
    op.create_index(
        op.f("ix_access_review_items_review_id"), "access_review_items", ["review_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_review_items_review_id"), table_name="access_review_items")
    op.drop_table("access_review_items")
    op.drop_index(op.f("ix_access_reviews_resource_id"), table_name="access_reviews")
    op.drop_table("access_reviews")
