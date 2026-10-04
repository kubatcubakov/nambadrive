"""Durable, rebuildable search index checkpoints; never authorization state."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SearchCheckpoint(Base):
    __tablename__ = "search_checkpoints"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    indexed_name: Mapped[str | None] = mapped_column(String(255))
    indexed_state: Mapped[str | None] = mapped_column(String(16))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
