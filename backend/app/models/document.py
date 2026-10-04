from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','CLEAN','INFECTED','REJECTED')"),
        CheckConstraint("size >= 0"),
        CheckConstraint("sequence_no > 0", name="ck_version_sequence"),
        CheckConstraint("NOT is_current OR status = 'CLEAN'", name="ck_current_clean"),
        UniqueConstraint("document_id", "sequence_no", name="uq_document_sequence"),
        Index(
            "uq_document_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        CheckConstraint("length(sha256) = 64"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    sequence_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    prune_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
