"""Document metadata and explicit trash restore permission (no role defaults)."""

import sqlalchemy as sa

from alembic import op

revision = "0007_documents"
down_revision = "0006_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_metadata",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("resources.id"), primary_key=True),
        sa.Column("project_id", sa.Uuid()),
        sa.Column("counterparty", sa.String(255)),
        sa.Column("contract_number", sa.String(255)),
        sa.Column("contract_date", sa.Date()),
        sa.Column("contract_expiry", sa.Date()),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text()),
    )
    op.create_index("ix_document_metadata_project_id", "document_metadata", ["project_id"])
    op.execute("INSERT INTO permissions(id) VALUES ('RESTORE')")


def downgrade() -> None:
    op.execute("DELETE FROM acl_entries WHERE permission_id = 'RESTORE'")
    op.execute("DELETE FROM role_permissions WHERE permission_id = 'RESTORE'")
    op.execute("DELETE FROM hard_policies WHERE permission_id = 'RESTORE'")
    op.execute("DELETE FROM break_glass_grants WHERE permission_id = 'RESTORE'")
    op.execute("DELETE FROM permissions WHERE id = 'RESTORE'")
    op.drop_table("document_metadata")
