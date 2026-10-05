"""bootstrap schema

Revision ID: 0001_bootstrap
Revises:
Create Date: 2026-10-05
"""

from collections.abc import Sequence

revision: str = "0001_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 0 deliberately creates no business tables.
    pass


def downgrade() -> None:
    pass
