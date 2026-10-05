"""Identity policy and durable ownership transfer queue."""

import sqlalchemy as sa

from alembic import op

revision = "0018_identity_lifecycle"
down_revision = "0017_access_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_policy",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("global_owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("id = 'GLOBAL'"),
    )
    op.create_table(
        "ownership_transfers",
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), primary_key=True),
        sa.Column("previous_owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.String())), [{"id": "MANAGE_IDENTITY"}]
    )


def downgrade() -> None:
    for table in ("acl_entries", "role_permissions", "hard_policies", "break_glass_grants"):
        column = "permission_id"
        op.execute(sa.text(f"DELETE FROM {table} WHERE {column} = 'MANAGE_IDENTITY'"))
    op.execute("DELETE FROM permissions WHERE id = 'MANAGE_IDENTITY'")
    op.drop_table("ownership_transfers")
    op.drop_table("identity_policy")
