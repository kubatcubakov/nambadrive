from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','CLEAN','INFECTED','REJECTED')"),
        CheckConstraint("size >= 0"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
