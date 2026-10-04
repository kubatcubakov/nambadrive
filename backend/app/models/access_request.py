import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccessRequest(Base):
    __tablename__ = "access_requests"
    __table_args__ = (
        CheckConstraint("permission_id IN ('VIEW','EDIT','DOWNLOAD')"),
        CheckConstraint("status IN ('PENDING','APPROVED','DENIED')"),
        CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL) OR "
            "(status != 'PENDING' AND decided_at IS NOT NULL AND decided_by IS NOT NULL)"
        ),
        Index(
            "uq_pending_access_request",
            "resource_id",
            "requested_by",
            "permission_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    permission_id: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))
    acl_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("acl_entries.id"))
