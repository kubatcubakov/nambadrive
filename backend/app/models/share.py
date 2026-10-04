import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExternalShare(Base):
    __tablename__ = "external_shares"
    __table_args__ = (
        CheckConstraint("views >= 0 AND (max_views IS NULL OR max_views > 0)"),
        CheckConstraint("allow_view OR allow_download"),
        CheckConstraint("expires_at > created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    allow_view: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=False)
    max_views: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
