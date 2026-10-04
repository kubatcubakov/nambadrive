"""Immutable numbered versions and a unique clean current version."""

import sqlalchemy as sa

from alembic import op

revision = "0008_versions"
down_revision = "0007_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "document_versions",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("document_versions", sa.Column("prune_after", sa.DateTime(timezone=True)))
    op.execute("""WITH numbered AS (
        SELECT id, row_number() OVER (PARTITION BY document_id ORDER BY created_at, id) AS number
        FROM document_versions
    ) UPDATE document_versions SET sequence_no =
        (SELECT number FROM numbered WHERE numbered.id=document_versions.id)""")
    op.execute("""UPDATE document_versions SET is_current=true WHERE status='CLEAN' AND NOT EXISTS (
        SELECT 1 FROM document_versions newer WHERE newer.document_id=document_versions.document_id
        AND newer.status='CLEAN' AND newer.sequence_no>document_versions.sequence_no)""")
    with op.batch_alter_table("document_versions") as batch:
        batch.create_check_constraint("ck_version_sequence", "sequence_no > 0")
        batch.create_check_constraint("ck_current_clean", "NOT is_current OR status = 'CLEAN'")
        batch.create_unique_constraint("uq_document_sequence", ["document_id", "sequence_no"])
    op.create_index(
        "uq_document_current",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )
    if op.get_context().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION immutable_document_version()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.id,NEW.document_id,NEW.space_id,NEW.uploaded_by,NEW.filename,NEW.mime_type,
                   NEW.size,NEW.sha256,NEW.sequence_no,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id,OLD.document_id,OLD.space_id,OLD.uploaded_by,OLD.filename,OLD.mime_type,
                   OLD.size,OLD.sha256,OLD.sequence_no,OLD.created_at) THEN
                RAISE EXCEPTION 'document version content metadata is immutable';
            END IF;
            IF OLD.status != 'PENDING' AND NEW.status != OLD.status THEN
                RAISE EXCEPTION 'final scan verdict is immutable';
            END IF;
            RETURN NEW;
        END $$""")
        op.execute("""CREATE TRIGGER immutable_version BEFORE UPDATE ON document_versions
            FOR EACH ROW EXECUTE FUNCTION immutable_document_version()""")


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TRIGGER immutable_version ON document_versions")
        op.execute("DROP FUNCTION immutable_document_version()")
    op.drop_index("uq_document_current", table_name="document_versions")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("uq_document_sequence", type_="unique")
        batch.drop_constraint("ck_current_clean", type_="check")
        batch.drop_constraint("ck_version_sequence", type_="check")
        batch.drop_column("prune_after")
        batch.drop_column("is_current")
        batch.drop_column("sequence_no")
