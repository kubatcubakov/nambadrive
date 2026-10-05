from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdentityPolicy(Base):
    __tablename__ = "identity_policy"
    __table_args__ = (CheckConstraint("id = 'GLOBAL'"),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="GLOBAL")
    global_owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class OwnershipTransfer(Base):
    __tablename__ = "ownership_transfers"
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    previous_owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
