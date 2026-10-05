from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id != id", name="department_not_self"),
        UniqueConstraint("company_id", "name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class DepartmentMembership(Base):
    __tablename__ = "department_memberships"
    __table_args__ = (
        CheckConstraint("kind IN ('PRIMARY', 'SECONDARY')"),
        Index(
            "one_primary_department",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'PRIMARY'"),
            sqlite_where=text("kind = 'PRIMARY'"),
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))


class DepartmentManager(Base):
    __tablename__ = "department_managers"
    __table_args__ = (CheckConstraint("valid_until IS NULL OR valid_until > valid_from"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), primary_key=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationAdministrator(Base):
    """Explicit local capability; never inferred from identity claims or department management."""

    __tablename__ = "organization_administrators"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
