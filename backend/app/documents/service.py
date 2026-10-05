from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, datetime
from typing import IO, Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService, utc
from app.documents.validation import filename
from app.governance.policy import bind_retention
from app.models.acl import HardPolicy
from app.models.document import DocumentVersion
from app.models.metadata import DocumentMetadata
from app.models.organization import Department
from app.models.resource import Resource
from app.models.user import User
from app.resources.service import ResourceService
from app.storage.seaweed import Area, ObjectKey, SeaweedStorage, StorageError

CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"]


class DocumentService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]) -> None:
        self.db, self.actor, self.context = db, actor, context

    async def require(self, document_id: uuid.UUID, permission: str) -> Resource:
        row = await self.db.get(Resource, document_id, with_for_update=True)
        decision = await AuthorizationService().authorize(
            self.db, self.actor, permission, document_id
        )
        if not decision.allowed:
            raise HTTPException(403, "Access denied")
        if row is None or row.resource_type != "DOCUMENT":
            raise ValueError("Document required")
        return row

    async def current(self, document_id: uuid.UUID) -> DocumentVersion:
        version = await self.db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == "CLEAN",
                DocumentVersion.is_current.is_(True),
            )
            .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
            .limit(1)
        )
        if version is None:
            raise HTTPException(404, "Document content unavailable")
        return version

    async def audit(self, event: str, row: Resource, **details: Any) -> None:
        await write_audit_event(
            event,
            user=str(self.actor.id),
            resource=str(row.id),
            result="success",
            **self.context,
            **details,
        )

    async def rename(self, document_id: uuid.UUID, name: str) -> Resource:
        row = await self.require(document_id, "RENAME")
        name = filename(name)
        if name.rsplit(".", 1)[-1].lower() != row.name.rsplit(".", 1)[-1].lower():
            raise ValueError("Renaming cannot change document format")
        old = row.name
        row.name = name
        await self.audit("rename", row, old_name=old, new_name=name)
        await self.db.commit()
        return row

    async def trash(self, document_id: uuid.UUID) -> None:
        row = await self.require(document_id, "DELETE")
        row.state, row.deleted_at = "TRASH", datetime.now(UTC)
        await self.audit("delete", row)
        await self.db.commit()

    async def restore(self, document_id: uuid.UUID) -> Resource:
        row = await self.require(document_id, "RESTORE")
        if row.state != "TRASH":
            raise ValueError("Document is not in trash")
        if not (
            await AuthorizationService().authorize(self.db, self.actor, "CREATE", row.parent_id)
        ).allowed:
            raise HTTPException(403, "Access denied")
        row.state, row.deleted_at = "ACTIVE", None
        await self.audit("restore", row)
        await self.db.commit()
        return row

    async def destination(self, row: Resource, target_id: uuid.UUID) -> list[Resource]:
        target = await self.db.get(Resource, target_id, with_for_update=True)
        if not (
            await AuthorizationService().authorize(self.db, self.actor, "CREATE", target_id)
        ).allowed:
            raise HTTPException(403, "Access denied")
        if target is None or target.resource_type not in {"SPACE", "FOLDER"}:
            raise ValueError("Invalid destination")
        source_dept = await self.db.get(Department, row.department_id)
        target_dept = await self.db.get(Department, target.department_id)
        if (
            source_dept is None
            or target_dept is None
            or source_dept.company_id != target_dept.company_id
        ):
            raise ValueError("Cross-company document movement is forbidden")
        return await ResourceService(self.db, self.actor, self.context).ancestors(target_id)

    async def preserve_policy(
        self, source: Resource, target: Resource, destination: list[Resource]
    ) -> None:
        chain = await ResourceService(self.db, self.actor, self.context).ancestors(source.id)
        target.classification = max(
            (r.classification for r in chain + destination), key=CLASSIFICATIONS.index
        )
        target.legal_hold = any(r.legal_hold for r in chain + destination)
        dates = [utc(r.retention_until) for r in chain + destination if r.retention_until]
        target.retention_until = max(dates) if dates else None
        # Moving/copying must not shed inherited hard prohibitions.
        policies = (
            await self.db.scalars(
                select(HardPolicy).where(HardPolicy.resource_id.in_([r.id for r in chain]))
            )
        ).all()
        existing = set(
            (
                await self.db.scalars(
                    select(HardPolicy.permission_id).where(HardPolicy.resource_id == target.id)
                )
            ).all()
        )
        for policy in policies:
            if policy.permission_id not in existing:
                self.db.add(
                    HardPolicy(
                        resource_id=target.id,
                        permission_id=policy.permission_id,
                        reason="Preserved source policy: " + policy.reason,
                    )
                )
                existing.add(policy.permission_id)

    async def move(self, document_id: uuid.UUID, target_id: uuid.UUID) -> Resource:
        row = await self.require(document_id, "MOVE")
        destination = await self.destination(row, target_id)
        old_parent = row.parent_id
        await self.preserve_policy(row, row, destination)
        row.parent_id = target_id
        row.department_id = destination[0].department_id
        await self.db.flush()
        await self.audit("move", row, old_parent=str(old_parent), new_parent=str(target_id))
        await self.db.commit()
        return row

    async def copy(
        self, document_id: uuid.UUID, target_id: uuid.UUID, storage: SeaweedStorage
    ) -> Resource:
        source = await self.require(document_id, "COPY")
        destination = await self.destination(source, target_id)
        version = await self.current(source.id)
        row = Resource(
            id=uuid.uuid4(),
            resource_type="DOCUMENT",
            name=source.name,
            owner_user_id=self.actor.id,
            department_id=destination[0].department_id,
            parent_id=target_id,
            classification=source.classification,
            state="ACTIVE",
        )
        self.db.add(row)
        await self.db.flush()
        await self.preserve_policy(source, row, destination)
        new_id = uuid.uuid4()
        with tempfile.TemporaryFile() as content:
            await run_in_threadpool(read_verified, storage, version, content)
            info = await run_in_threadpool(
                storage.put, ObjectKey(destination[-1].id, row.id, new_id), content, Area.DATA
            )
        self.db.add(
            DocumentVersion(
                id=new_id,
                document_id=row.id,
                space_id=destination[-1].id,
                uploaded_by=self.actor.id,
                filename=row.name,
                mime_type=version.mime_type,
                size=info.size,
                sha256=info.sha256,
                status="CLEAN",
                is_current=True,
                scanned_at=version.scanned_at,
                retention_until=version.retention_until,
            )
        )
        metadata = await self.db.get(DocumentMetadata, source.id)
        if metadata:
            self.db.add(
                DocumentMetadata(
                    document_id=row.id,
                    **{
                        c.name: getattr(metadata, c.name)
                        for c in metadata.__table__.columns
                        if c.name != "document_id"
                    },
                )
            )
        await self.db.flush()
        await bind_retention(self.db, await self.current(row.id))
        await self.audit("copy", row, source_document=str(source.id))
        await self.db.commit()
        return row


def read_verified(
    storage: SeaweedStorage, version: DocumentVersion, destination: IO[bytes]
) -> None:
    """Verify the complete object before returning any bytes to a user or another consumer."""
    digest, size = hashlib.sha256(), 0
    key = ObjectKey(version.space_id, version.document_id, version.id)
    for chunk in storage.read(key, Area.DATA):
        size += len(chunk)
        if size > version.size:
            raise StorageError("Document integrity failure")
        digest.update(chunk)
        destination.write(chunk)
    if size != version.size or digest.hexdigest() != version.sha256:
        raise StorageError("Document integrity failure")
    destination.seek(0)
