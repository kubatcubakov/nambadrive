"""Hashed external share capabilities with bounded lifetimes and usage."""

import sqlalchemy as sa

from alembic import op

revision = "0011_shares"
down_revision = "0010_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(200)),
        sa.Column("allow_view", sa.Boolean(), nullable=False),
        sa.Column("allow_download", sa.Boolean(), nullable=False),
        sa.Column("max_views", sa.Integer()),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("views >= 0 AND (max_views IS NULL OR max_views > 0)"),
        sa.CheckConstraint("allow_view OR allow_download"),
        sa.CheckConstraint("expires_at > created_at"),
    )
    op.create_index("ix_external_shares_document_id", "external_shares", ["document_id"])
    op.create_index("ix_external_shares_created_by", "external_shares", ["created_by"])
    if op.get_context().dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_share_max_lifetime",
            "external_shares",
            "expires_at <= created_at + interval '30 days'",
        )


def downgrade() -> None:
    op.drop_table("external_shares")
