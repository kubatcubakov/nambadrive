"""Organization structure and explicit administration capability."""

import sqlalchemy as sa

from alembic import op

revision = "0003_organization"
down_revision = "0002_identity_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("departments.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id != id", name="department_not_self"),
        sa.UniqueConstraint("company_id", "name"),
    )
    op.create_table(
        "department_memberships",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.CheckConstraint("kind IN ('PRIMARY', 'SECONDARY')"),
    )
    op.create_index(
        "one_primary_department",
        "department_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'PRIMARY'"),
        sqlite_where=sa.text("kind = 'PRIMARY'"),
    )
    op.create_table(
        "department_managers",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), primary_key=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > valid_from"),
    )
    op.create_table(
        "organization_administrators",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )


def downgrade() -> None:
    for table in (
        "organization_administrators",
        "department_managers",
        "department_memberships",
        "departments",
        "companies",
    ):
        op.drop_table(table)
