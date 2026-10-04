from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.authorization.service import utc
from app.documents.service import DocumentService, read_verified
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.models.user import User
from app.resources.service import ResourceService
from app.storage.seaweed import Area, ObjectKey, SeaweedStorage


async def next_sequence(db: AsyncSession, document_id: uuid.UUID) -> int:
    """Caller holds the document row lock throughout allocation and commit."""
    number = await db.scalar(
        select(func.max(DocumentVersion.sequence_no)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return (number or 0) + 1


async def promote(
    db: AsyncSession, actor: User, document: Resource, version: DocumentVersion
) -> None:
    """Caller holds document lock; out-of-order AV completion never rolls current back."""
    versions = list(
        (
            await db.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document.id, DocumentVersion.status == "CLEAN"
                )
                .order_by(DocumentVersion.sequence_no.desc())
            )
        ).all()
    )
    if version not in versions:
        versions.append(version)
    versions.sort(key=lambda v: v.sequence_no, reverse=True)
    newest = versions[0]
    for item in versions:
        if item.is_current and item.id != newest.id:
            item.is_current = False
    await db.flush()
    newest.is_current = True
    chain = await ResourceService(db, actor, {}).ancestors(document.id)
    protected = any(
        row.legal_hold or (row.retention_until and utc(row.retention_until) > datetime.now(UTC))
        for row in chain
    )
    for index, item in enumerate(versions):
        if index < 3 or protected:
            item.prune_after = None
        elif item.prune_after is None:
            item.prune_after = datetime.now(UTC) + timedelta(days=30)
    await db.flush()


class VersionService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]) -> None:
        self.db, self.actor, self.context = db, actor, context
        self.documents = DocumentService(db, actor, context)

    async def history(self, document_id: uuid.UUID) -> list[DocumentVersion]:
        await self.documents.require(document_id, "VIEW_VERSION_HISTORY")
        return list(
            (
                await self.db.scalars(
                    select(DocumentVersion)
                    .where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.status == "CLEAN",
                        DocumentVersion.prune_after.is_(None),
                    )
                    .order_by(DocumentVersion.sequence_no.desc())
                )
            ).all()
        )

    async def restore(
        self, document_id: uuid.UUID, version_id: uuid.UUID, storage: SeaweedStorage
    ) -> DocumentVersion:
        document = await self.documents.require(document_id, "RESTORE_VERSION")
        source = await self.db.get(DocumentVersion, version_id)
        if (
            source is None
            or source.document_id != document.id
            or source.status != "CLEAN"
            or source.prune_after is not None
        ):
            raise ValueError("Version unavailable")
        chain = await ResourceService(self.db, self.actor, self.context).ancestors(document_id)
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            space_id=chain[-1].id,
            uploaded_by=self.actor.id,
            filename=document.name,
            mime_type=source.mime_type,
            size=source.size,
            sha256=source.sha256,
            status="CLEAN",
            scanned_at=source.scanned_at,
            sequence_no=await next_sequence(self.db, document.id),
            is_current=False,
        )
        with tempfile.TemporaryFile() as content:
            await run_in_threadpool(read_verified, storage, source, content)
            await run_in_threadpool(
                storage.put,
                ObjectKey(version.space_id, document.id, version.id),
                content,
                Area.DATA,
            )
        self.db.add(version)
        await self.db.flush()
        await promote(self.db, self.actor, document, version)
        await self.documents.audit(
            "edit",
            document,
            operation="restore_version",
            source_version=str(source.id),
            version=str(version.id),
        )
        await self.db.commit()
        return version
