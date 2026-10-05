from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    counterparty: Mapped[str | None] = mapped_column(String(255))
    contract_number: Mapped[str | None] = mapped_column(String(255))
    contract_date: Mapped[date | None] = mapped_column(Date)
    contract_expiry: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text)
