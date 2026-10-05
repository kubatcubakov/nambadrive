"""Atomic user/department/project quotas and durable storage write reservations."""

import sqlalchemy as sa

from alembic import op

revision = "0014_quotas"
down_revision = "0013_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_projects_company_id", "projects", ["company_id"])
    # Preserve legacy optional UUIDs. Operators can reconcile inactive imported projects;
    # no existing document metadata is dropped or assigned to an invented company.
    op.execute(
        "INSERT INTO projects (id,name,enabled) "
        "SELECT DISTINCT project_id,'Imported project',false "
        "FROM document_metadata WHERE project_id IS NOT NULL"
    )
    with op.batch_alter_table("document_metadata") as batch:
        batch.create_foreign_key("fk_document_project", "projects", ["project_id"], ["id"])
    op.create_table(
        "quota_limits",
        sa.Column("subject_type", sa.String(16), primary_key=True),
        sa.Column("subject_id", sa.Uuid(), primary_key=True),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("subject_type IN ('USER','DEPARTMENT','PROJECT')"),
        sa.CheckConstraint("limit_bytes >= 0"),
    )
    op.create_table(
        "storage_reservations",
        sa.Column("version_id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid()),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("area", sa.String(16), nullable=False),
        sa.Column("policy_scope_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("size >= 0"),
        sa.CheckConstraint("area IN ('quarantine','data')"),
    )
    for field in ["document_id", "owner_id", "department_id", "project_id"]:
        op.create_index("ix_storage_reservations_" + field, "storage_reservations", [field])
    op.create_table(
        "quota_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("requested_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(sa.table("permissions", sa.column("id", sa.String())), [{"id": "MANAGE_QUOTAS"}])


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE id = 'MANAGE_QUOTAS'")
    op.drop_table("quota_incidents")
    op.drop_table("storage_reservations")
    op.drop_table("quota_limits")
    with op.batch_alter_table("document_metadata") as batch:
        batch.drop_constraint("fk_document_project", type_="foreignkey")
    op.drop_table("projects")
