from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.documents.service import read_verified
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.models.search import SearchCheckpoint
from app.search.clients import OpenSearch, SearchUnavailable, Tika
from app.storage.seaweed import SeaweedStorage, StorageError

FULLTEXT = {"docx", "xlsx", "pdf", "txt", "csv", "json", "xml"}


class Indexer:
    def __init__(self, db: AsyncSession, storage: SeaweedStorage, tika: Tika, index: OpenSearch):
        self.db, self.storage, self.tika, self.index = db, storage, tika, index

    async def process_one(self) -> bool:
        now = datetime.now(UTC)
        selection = await self.db.execute(
            select(Resource, DocumentVersion, SearchCheckpoint)
            .outerjoin(
                DocumentVersion,
                (DocumentVersion.document_id == Resource.id)
                & DocumentVersion.is_current.is_(True)
                & (DocumentVersion.status == "CLEAN"),
            )
            .outerjoin(SearchCheckpoint, SearchCheckpoint.document_id == Resource.id)
            .where(
                Resource.resource_type == "DOCUMENT",
                or_(
                    SearchCheckpoint.document_id.is_(None),
                    SearchCheckpoint.version_id.is_distinct_from(DocumentVersion.id),
                    SearchCheckpoint.indexed_name.is_distinct_from(Resource.name),
                    SearchCheckpoint.indexed_state.is_distinct_from(Resource.state),
                ),
                or_(SearchCheckpoint.retry_after.is_(None), SearchCheckpoint.retry_after <= now),
            )
            .order_by(Resource.id)
            .limit(1)
            .with_for_update(of=Resource, skip_locked=True)
        )
        item = selection.first()
        if item is None:
            return False
        row, version, checkpoint = item
        if checkpoint is None:
            checkpoint = SearchCheckpoint(document_id=row.id)
            self.db.add(checkpoint)
        try:
            if row.state != "ACTIVE" or version is None:
                await run_in_threadpool(self.index.delete, row.id)
            else:
                content = ""
                if version.filename.rsplit(".", 1)[-1].lower() in FULLTEXT:
                    with tempfile.TemporaryFile() as source:
                        await run_in_threadpool(read_verified, self.storage, version, source)
                        content = await run_in_threadpool(
                            self.tika.extract, source, version.mime_type
                        )
                await run_in_threadpool(self.index.put, row.id, version.id, row.name, content)
            checkpoint.version_id = version.id if version else None
            checkpoint.indexed_name, checkpoint.indexed_state = row.name, row.state
            checkpoint.retry_after = None
        except (SearchUnavailable, StorageError, OSError):
            checkpoint.retry_after = now + timedelta(minutes=5)
            await self.db.commit()
            raise
        await self.db.commit()
        return True
