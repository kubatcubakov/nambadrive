"""Private favorites and recent document metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0019_drive_dashboard"
down_revision = "0018_identity_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in [("favorites", "created_at"), ("recent_documents", "viewed_at")]:
        op.create_table(
            table,
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), primary_key=True),
            sa.Column(
                column,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now() if table == "favorites" else None,
            ),
        )


def downgrade() -> None:
    op.drop_table("recent_documents")
    op.drop_table("favorites")
