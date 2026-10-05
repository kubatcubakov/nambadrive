from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("resource_type IN ('SPACE','FOLDER','DOCUMENT')"),
        CheckConstraint(
            "classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','STRICTLY_CONFIDENTIAL')"
        ),
        CheckConstraint("state IN ('ACTIVE','QUARANTINED','TRASH')"),
        CheckConstraint("parent_id IS NULL OR parent_id != id"),
        CheckConstraint(
            "(resource_type = 'SPACE' AND parent_id IS NULL) OR "
            "(resource_type != 'SPACE' AND parent_id IS NOT NULL)"
        ),
        CheckConstraint(
            "(state = 'TRASH' AND deleted_at IS NOT NULL) OR "
            "(state != 'TRASH' AND deleted_at IS NULL)"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"), index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    inherit_acl: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    classification: Mapped[str] = mapped_column(
        String(32), default="INTERNAL", server_default="INTERNAL"
    )
    state: Mapped[str] = mapped_column(String(16), default="ACTIVE", server_default="ACTIVE")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Policy metadata for the mandatory Phase 4 pre-grant checks; no policy mutation API yet.
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
