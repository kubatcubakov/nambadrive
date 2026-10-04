from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class RoleBinding(Base):
    __tablename__ = "role_bindings"
    __table_args__ = (CheckConstraint("valid_until IS NULL OR valid_until > valid_from"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ACLEntry(Base):
    __tablename__ = "acl_entries"
    __table_args__ = (
        CheckConstraint("principal_type IN ('USER','DEPARTMENT','ROLE')"),
        CheckConstraint("effect IN ('ALLOW','DENY')"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from"),
        CheckConstraint("applies_to_self OR propagate_to_children"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    principal_type: Mapped[str] = mapped_column(String(16))
    principal_id: Mapped[uuid.UUID] = mapped_column()
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"))
    effect: Mapped[str] = mapped_column(String(8))
    applies_to_self: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    propagate_to_children: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), default="EXPLICIT", server_default="EXPLICIT")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)


class HardPolicy(Base):
    __tablename__ = "hard_policies"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"))
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"))
    reason: Mapped[str] = mapped_column(Text)


class BreakGlassGrant(Base):
    __tablename__ = "break_glass_grants"
    __table_args__ = (
        CheckConstraint("valid_until > valid_from"),
        CheckConstraint("length(reason) > 0"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"))
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    audited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
