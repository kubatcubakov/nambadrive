from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.documents.service import read_verified
from app.governance.policy import governance_lock, schedule_pruning
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.storage.seaweed import Area, ObjectKey, SeaweedStorage, StorageError


class CleanupWorker:
    def __init__(self, db: AsyncSession, storage: SeaweedStorage):
        self.db, self.storage = db, storage

    async def process_one(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        await governance_lock(self.db)
        versions = (
            await self.db.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.purged_at.is_(None),
                    or_(
                        DocumentVersion.cleanup_retry_after.is_(None),
                        DocumentVersion.cleanup_retry_after <= now,
                    ),
                )
                .order_by(DocumentVersion.created_at, DocumentVersion.id)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for version in versions:
            row = await self.db.get(
                Resource, version.document_id, with_for_update=True, populate_existing=True
            )
            if row is None:
                raise StorageError("Cleanup metadata unavailable")
            await schedule_pruning(self.db, row.id)
            full = await AuthorizationService().authorize_cleanup(self.db, version, now=now)
            quarantine = await AuthorizationService().authorize_cleanup(
                self.db, version, quarantine_only=True, now=now
            )
            if not full.allowed and not quarantine.allowed:
                version.cleanup_retry_after = now + timedelta(hours=6)
                continue
            version_id = version.id
            try:
                await self.remove(version, row, not full.allowed, now)
            except (StorageError, OSError):
                await self.db.rollback()
                retry = await self.db.get(DocumentVersion, version_id, with_for_update=True)
                if retry is not None:
                    retry.cleanup_retry_after = now + timedelta(minutes=5)
                    await self.db.commit()
                raise
            return True
        await self.db.commit()
        return bool(versions)

    async def remove(
        self, version: DocumentVersion, row: Resource, quarantine_only: bool, now: datetime
    ) -> None:
        # No public API calls this worker. Policy/hierarchy lock remains held through deletion.
        if quarantine_only:
            # Never delete the extra clean copy until the data copy's full bytes verify.
            with tempfile.TemporaryFile() as content:
                await run_in_threadpool(read_verified, self.storage, version, content)
        if not quarantine_only and version.purge_started_at is None:
            version.purge_started_at = now
            if row.state in {"TRASH", "QUARANTINED"}:
                row.purge_started_at = now
            await write_audit_event(
                "purge_scheduled",
                user=None,
                resource=str(row.id),
                version=str(version.id),
                result="authorized",
                correlation_id=str(uuid.uuid4()),
                ip=None,
                user_agent="cleanup-worker",
            )
            await self.db.commit()
            # Durable intent prevents restoring partly deleted data after a failed storage call.
            # Reacquire policy/row locks and recheck any hold added between transactions.
            await governance_lock(self.db)
            await self.db.refresh(row, with_for_update=True)
            await self.db.refresh(version, with_for_update=True)
            decision = await AuthorizationService().authorize_cleanup(self.db, version, now=now)
            if not decision.allowed:
                version.cleanup_retry_after = now + timedelta(hours=6)
                await self.db.commit()
                return
        event_id = str(uuid.uuid4())
        context = {
            "correlation_id": event_id,
            "user": None,
            "ip": None,
            "user_agent": "cleanup-worker",
            "resource": str(row.id),
            "version": str(version.id),
            "areas": ["quarantine"] if quarantine_only else ["data", "quarantine"],
        }
        # Validate/flush all DB metadata changes before touching storage. Audit intent survives
        # a storage/commit failure; completed events permit reconciliation without deleting history.
        version.quarantine_purged_at = now
        version.cleanup_retry_after = None
        if not quarantine_only:
            version.purged_at, version.is_current = now, False
            other = await self.db.scalar(
                select(DocumentVersion.id)
                .where(
                    DocumentVersion.document_id == row.id,
                    DocumentVersion.id != version.id,
                    DocumentVersion.purged_at.is_(None),
                )
                .limit(1)
            )
            if other is None:
                row.purged_at = now
        await self.db.flush()
        await write_audit_event("purge_started", result="authorized", **context)
        key = ObjectKey(version.space_id, row.id, version.id)
        if not quarantine_only:
            # Confirm the DB transaction/lock is still alive before each irreversible call.
            await self.db.execute(select(1))
            await run_in_threadpool(self.storage.delete, key, Area.DATA)
        await self.db.execute(select(1))
        await run_in_threadpool(self.storage.delete, key, Area.QUARANTINE)
        await write_audit_event("purge_completed", result="success", **context)
        await self.db.commit()
