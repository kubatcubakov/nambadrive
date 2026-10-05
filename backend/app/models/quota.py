import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class QuotaLimit(Base):
    __tablename__ = "quota_limits"
    __table_args__ = (
        CheckConstraint("subject_type IN ('USER','DEPARTMENT','PROJECT')"),
        CheckConstraint("limit_bytes >= 0"),
    )
    subject_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    limit_bytes: Mapped[int] = mapped_column(BigInteger)


class StorageReservation(Base):
    """Independent write-ahead charge: deliberately no FK to uncommitted resource metadata."""

    __tablename__ = "storage_reservations"
    __table_args__ = (
        CheckConstraint("size >= 0"),
        CheckConstraint("area IN ('quarantine','data')"),
    )
    version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    space_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    area: Mapped[str] = mapped_column(String(16))
    policy_scope_ids: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaIncident(Base):
    __tablename__ = "quota_incidents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column()
    resource_id: Mapped[uuid.UUID] = mapped_column()
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[uuid.UUID] = mapped_column()
    limit_bytes: Mapped[int] = mapped_column(BigInteger)
    requested_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
