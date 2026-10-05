from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OfficeRoom(Base):
    __tablename__ = "office_rooms"
    __table_args__ = (
        Index(
            "uq_office_active_room",
            "document_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    base_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfficeSession(Base):
    __tablename__ = "office_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("office_rooms.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    application_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application_sessions.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfficeSave(Base):
    __tablename__ = "office_saves"
    __table_args__ = (UniqueConstraint("room_id", "callback_hash", name="uq_office_callback"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("office_rooms.id"), index=True)
    callback_hash: Mapped[str] = mapped_column(String(64))
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id"))
