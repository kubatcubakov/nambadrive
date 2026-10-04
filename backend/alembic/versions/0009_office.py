"""ONLYOFFICE shared rooms, expiring actor sessions and callback idempotency."""

import sqlalchemy as sa

from alembic import op

revision = "0009_office"
down_revision = "0008_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(
            sa.Column(
                "ingest_permission",
                sa.String(32),
                nullable=False,
                server_default="UPLOAD_NEW_VERSION",
            )
        )
        batch.create_check_constraint(
            "ck_version_ingest", "ingest_permission IN ('CREATE','UPLOAD_NEW_VERSION','EDIT')"
        )
    if op.get_context().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION immutable_version_ingest()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.ingest_permission != OLD.ingest_permission THEN
                RAISE EXCEPTION 'version ingest authorization is immutable';
            END IF;
            RETURN NEW;
        END $$""")
        op.execute(
            "CREATE TRIGGER immutable_ingest BEFORE UPDATE ON document_versions "
            "FOR EACH ROW EXECUTE FUNCTION immutable_version_ingest()"
        )
    op.create_table(
        "office_rooms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column(
            "base_version_id", sa.Uuid(), sa.ForeignKey("document_versions.id"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_office_rooms_document_id", "office_rooms", ["document_id"])
    op.create_index(
        "uq_office_active_room",
        "office_rooms",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
        sqlite_where=sa.text("closed_at IS NULL"),
    )
    op.create_table(
        "office_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("room_id", sa.Uuid(), sa.ForeignKey("office_rooms.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "application_session_id",
            sa.Uuid(),
            sa.ForeignKey("application_sessions.id"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_office_sessions_room_id", "office_sessions", ["room_id"])
    op.create_index("ix_office_sessions_user_id", "office_sessions", ["user_id"])
    op.create_table(
        "office_saves",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("room_id", sa.Uuid(), sa.ForeignKey("office_rooms.id"), nullable=False),
        sa.Column("callback_hash", sa.String(64), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_versions.id")),
        sa.UniqueConstraint("room_id", "callback_hash", name="uq_office_callback"),
    )
    op.create_index("ix_office_saves_room_id", "office_saves", ["room_id"])


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TRIGGER immutable_ingest ON document_versions")
        op.execute("DROP FUNCTION immutable_version_ingest()")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("ck_version_ingest", type_="check")
        batch.drop_column("ingest_permission")
    op.drop_table("office_saves")
    op.drop_table("office_sessions")
    op.drop_table("office_rooms")
