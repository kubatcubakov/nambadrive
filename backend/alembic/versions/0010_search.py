"""Durable search indexing checkpoints."""

import sqlalchemy as sa

from alembic import op

revision = "0010_search"
down_revision = "0009_office"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_checkpoints",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("resources.id"), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_versions.id")),
        sa.Column("indexed_name", sa.String(255)),
        sa.Column("indexed_state", sa.String(16)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("search_checkpoints")
