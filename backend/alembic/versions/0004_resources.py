"""Unified metadata security resource tree; no binary access."""

import sqlalchemy as sa

from alembic import op

revision = "0004_resources"
down_revision = "0003_organization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("resources.id")),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("inherit_acl", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("classification", sa.String(32), nullable=False, server_default="INTERNAL"),
        sa.Column("state", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint("resource_type IN ('SPACE','FOLDER','DOCUMENT')"),
        sa.CheckConstraint(
            "classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','STRICTLY_CONFIDENTIAL')"
        ),
        sa.CheckConstraint("state IN ('ACTIVE','QUARANTINED','TRASH')"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id != id"),
        sa.CheckConstraint(
            "(resource_type = 'SPACE' AND parent_id IS NULL) "
            "OR (resource_type != 'SPACE' AND parent_id IS NOT NULL)"
        ),
        sa.CheckConstraint(
            "(state = 'TRASH' AND deleted_at IS NOT NULL) "
            "OR (state != 'TRASH' AND deleted_at IS NULL)"
        ),
    )
    for column in ("parent_id", "owner_user_id", "department_id"):
        op.create_index("ix_resources_" + column, "resources", [column])
    # PostgreSQL trigger enforces tree shape and cycles for trusted DB writers too.
    if op.get_context().dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION validate_resource_tree() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_kind text;
        BEGIN
            -- Serialize hierarchy mutation to avoid concurrent write-skew cycles.
            PERFORM pg_advisory_xact_lock(735904);
            IF NEW.parent_id IS NOT NULL THEN
                SELECT resource_type INTO parent_kind FROM resources WHERE id = NEW.parent_id;
                IF parent_kind IS NULL OR parent_kind NOT IN ('SPACE', 'FOLDER') THEN
                    RAISE EXCEPTION 'invalid resource parent';
                END IF;
                IF EXISTS (WITH RECURSIVE ancestors AS (
                    SELECT id, parent_id FROM resources WHERE id = NEW.parent_id
                    UNION SELECT r.id, r.parent_id FROM resources r
                    JOIN ancestors a ON r.id = a.parent_id
                ) SELECT 1 FROM ancestors WHERE id = NEW.id) THEN
                    RAISE EXCEPTION 'resource cycle';
                END IF;
            END IF;
            IF NEW.resource_type = 'DOCUMENT' AND EXISTS (
                SELECT 1 FROM resources WHERE parent_id = NEW.id) THEN
                RAISE EXCEPTION 'document cannot have children';
            END IF;
            RETURN NEW;
        END $$;
        """)
        op.execute(
            "CREATE TRIGGER resource_tree_check BEFORE INSERT OR UPDATE ON resources "
            "FOR EACH ROW EXECUTE FUNCTION validate_resource_tree()"
        )


def downgrade() -> None:
    op.drop_table("resources")
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP FUNCTION validate_resource_tree()")
