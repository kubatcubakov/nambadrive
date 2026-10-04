from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.documents.antivirus import ClamAV, ScanUnavailable
from app.documents.service import DocumentService
from app.documents.validation import filename, validate
from app.documents.versions import next_sequence, promote
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.models.user import User
from app.resources.service import ResourceService
from app.storage.seaweed import Area, ObjectExists, ObjectKey, SeaweedStorage, StorageError


class UploadService:
    def __init__(self, db: AsyncSession, storage: SeaweedStorage) -> None:
        self.db, self.storage = db, storage

    async def create(
        self,
        actor: User,
        parent_id: uuid.UUID,
        name: str,
        source: BinaryIO,
        context: dict[str, Any],
    ) -> DocumentVersion:
        parent = await self.db.get(Resource, parent_id, with_for_update=True)
        decision = await AuthorizationService().authorize(self.db, actor, "CREATE", parent_id)
        if not decision.allowed:
            raise HTTPException(403, "Access denied")
        if parent is None or parent.resource_type not in {"SPACE", "FOLDER"}:
            raise ValueError("Invalid document parent")
        name = filename(name)
        mime = await run_in_threadpool(validate, source, name, self.storage.max_bytes)
        chain = await ResourceService(self.db, actor, context).ancestors(parent_id)
        document = Resource(
            id=uuid.uuid4(),
            resource_type="DOCUMENT",
            name=name,
            parent_id=parent.id,
            owner_user_id=actor.id,
            department_id=parent.department_id,
            classification=parent.classification,
            state="QUARANTINED",
        )
        self.db.add(document)
        await self.db.flush()
        version_id = uuid.uuid4()
        key = ObjectKey(chain[-1].id, document.id, version_id)
        info = await run_in_threadpool(self.storage.put, key, source)
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            space_id=chain[-1].id,
            uploaded_by=actor.id,
            filename=name,
            mime_type=mime,
            size=info.size,
            sha256=info.sha256,
            status="PENDING",
        )
        self.db.add(version)
        await self.db.flush()
        await write_audit_event(
            "upload",
            user=str(actor.id),
            resource=str(document.id),
            result="quarantined",
            version=str(version.id),
            **context,
        )
        await self.db.commit()
        return version

    async def new_version(
        self,
        actor: User,
        document_id: uuid.UUID,
        name: str,
        source: BinaryIO,
        context: dict[str, Any],
    ) -> DocumentVersion:
        document = await DocumentService(self.db, actor, context).require(
            document_id, "UPLOAD_NEW_VERSION"
        )
        name = filename(name)
        if name.rsplit(".", 1)[-1].lower() != document.name.rsplit(".", 1)[-1].lower():
            raise ValueError("New version must retain document format")
        mime = await run_in_threadpool(validate, source, name, self.storage.max_bytes)
        chain = await ResourceService(self.db, actor, context).ancestors(document.id)
        version_id = uuid.uuid4()
        info = await run_in_threadpool(
            self.storage.put, ObjectKey(chain[-1].id, document.id, version_id), source
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            space_id=chain[-1].id,
            uploaded_by=actor.id,
            filename=name,
            mime_type=mime,
            size=info.size,
            sha256=info.sha256,
            status="PENDING",
            sequence_no=await next_sequence(self.db, document.id),
        )
        self.db.add(version)
        await self.db.flush()
        await write_audit_event(
            "upload",
            user=str(actor.id),
            resource=str(document.id),
            result="quarantined",
            version=str(version.id),
            **context,
        )
        await self.db.commit()
        return version

    async def scan_one(self, scanner: ClamAV) -> bool:
        """Durable DB queue; locks prevent concurrent promotion. Retry after any outage."""
        version = await self.db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.status == "PENDING",
                or_(
                    DocumentVersion.retry_after.is_(None),
                    DocumentVersion.retry_after <= datetime.now(UTC),
                ),
            )
            .order_by(DocumentVersion.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if version is None:
            return False
        version_id = version.id
        try:
            return await self._scan(version, scanner)
        except (StorageError, ScanUnavailable, OSError):
            await self.db.rollback()
            retry = await self.db.get(DocumentVersion, version_id, with_for_update=True)
            if retry is not None and retry.status == "PENDING":
                retry.retry_after = datetime.now(UTC) + timedelta(minutes=5)
                await self.db.commit()
            raise

    async def _scan(self, version: DocumentVersion, scanner: ClamAV) -> bool:
        document = await self.db.get(Resource, version.document_id, with_for_update=True)
        actor = await self.db.get(User, version.uploaded_by)
        if document is None or actor is None:
            raise StorageError("Upload metadata unavailable")
        parent_id = document.parent_id
        if parent_id is not None:
            await self.db.get(Resource, parent_id, with_for_update=True)
        permission, target_id = (
            ("CREATE", parent_id)
            if document.state == "QUARANTINED"
            else ("UPLOAD_NEW_VERSION", document.id)
        )
        allowed = await AuthorizationService().authorize(self.db, actor, permission, target_id)
        if document.state not in {"QUARANTINED", "ACTIVE"} or not allowed.allowed:
            version.status = "REJECTED"
            await write_audit_event(
                "upload",
                user=str(actor.id),
                resource=str(document.id),
                result="rejected",
                version=str(version.id),
            )
            await self.db.commit()
            return True
        key = ObjectKey(version.space_id, document.id, version.id)
        with tempfile.TemporaryFile() as source:

            def retrieve() -> None:
                digest, size = hashlib.sha256(), 0
                for chunk in self.storage.read(key, Area.QUARANTINE):
                    size += len(chunk)
                    if size > version.size or size > self.storage.max_bytes:
                        raise StorageError("Quarantine integrity failure")
                    source.write(chunk)
                    digest.update(chunk)
                if size != version.size or digest.hexdigest() != version.sha256:
                    raise StorageError("Quarantine integrity failure")
                source.seek(0)

            await run_in_threadpool(retrieve)
            clean = await run_in_threadpool(scanner.scan, source)
            if clean:
                try:
                    await run_in_threadpool(self.storage.put, key, source, Area.DATA)
                except ObjectExists:
                    # Reconcile a successful S3 write followed by a DB rollback. Never overwrite.
                    info = await run_in_threadpool(self.storage.stat, key, Area.DATA)
                    if info.sha256 != version.sha256 or info.size != version.size:
                        raise StorageError("Promotion integrity failure") from None
                version.status = "CLEAN"
                document.state = "ACTIVE"
                await promote(self.db, actor, document, version)
            else:
                version.status = "INFECTED"
            version.scanned_at = datetime.now(UTC)
            await write_audit_event(
                "upload" if clean else "malware_detected",
                user=str(actor.id),
                resource=str(document.id),
                result="active" if clean else "blocked",
                version=str(version.id),
            )
            await self.db.commit()
        # Keep quarantine bytes for governed cleanup; do not bypass hold/retention here.
        return True
