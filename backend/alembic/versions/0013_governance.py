"""Retention policy, historical Legal Hold and recoverable cleanup metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0013_governance"
down_revision = "0012_access_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("purged_at", sa.DateTime(timezone=True)))
    op.add_column("resources", sa.Column("purge_started_at", sa.DateTime(timezone=True)))
    for column in [
        "retention_until",
        "purged_at",
        "quarantine_purged_at",
        "cleanup_retry_after",
        "purge_started_at",
    ]:
        op.add_column("document_versions", sa.Column(column, sa.DateTime(timezone=True)))
    op.create_table(
        "retention_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id")),
        sa.Column("document_type", sa.String(10)),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(2000)),
        sa.CheckConstraint("days >= 1 AND days <= 36500"),
    )
    op.create_index("ix_retention_policies_resource_id", "retention_policies", ["resource_id"])
    op.create_table(
        "legal_hold_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_legal_hold_events_resource_id", "legal_hold_events", ["resource_id"])
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.String())),
        [{"id": "MANAGE_RETENTION"}, {"id": "MANAGE_LEGAL_HOLD"}],
    )
    if op.get_context().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION preserve_retention_deadline()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.retention_until IS NOT NULL AND
                (NEW.retention_until IS NULL OR NEW.retention_until < OLD.retention_until) THEN
                RAISE EXCEPTION 'materialized version retention cannot be shortened';
            END IF;
            RETURN NEW;
        END $$""")
        op.execute(
            "CREATE TRIGGER preserve_version_retention BEFORE UPDATE ON document_versions "
            "FOR EACH ROW EXECUTE FUNCTION preserve_retention_deadline()"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TRIGGER preserve_version_retention ON document_versions")
        op.execute("DROP FUNCTION preserve_retention_deadline()")
    op.execute("DELETE FROM permissions WHERE id IN ('MANAGE_RETENTION','MANAGE_LEGAL_HOLD')")
    op.drop_table("legal_hold_events")
    op.drop_table("retention_policies")
    with op.batch_alter_table("document_versions") as batch:
        for column in [
            "retention_until",
            "purged_at",
            "quarantine_purged_at",
            "cleanup_retry_after",
            "purge_started_at",
        ]:
            batch.drop_column(column)
    with op.batch_alter_table("resources") as batch:
        batch.drop_column("purged_at")
        batch.drop_column("purge_started_at")
