from __future__ import annotations

import hashlib
import uuid
from typing import Any, BinaryIO

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.governance.policy import chain, governance_lock
from app.models.document import DocumentVersion
from app.models.metadata import DocumentMetadata
from app.models.organization import Company, Department
from app.models.quota import Project, QuotaIncident, QuotaLimit, StorageReservation
from app.models.resource import Resource
from app.models.user import User
from app.storage.seaweed import Area, ObjectInfo, ObjectKey


def fingerprint(source: BinaryIO) -> ObjectInfo:
    source.seek(0)
    size, digest = 0, hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    source.seek(0)
    return ObjectInfo(size, digest.hexdigest())


async def durable_record(db: AsyncSession, row: StorageReservation | QuotaIncident) -> None:
    if db.get_bind().dialect.name != "postgresql":
        # SQLite is only the unit adapter; PostgreSQL runtime gates test independent durability.
        db.add(row)
        await db.flush()
        return
    bind = db.bind.engine if isinstance(db.bind, AsyncConnection) else db.bind
    if bind is None:
        raise RuntimeError("Database required")
    # Separate pool: waiting request transactions cannot exhaust connections needed by
    # the one lock holder's autonomous journal writer.
    journal_engine = create_async_engine(bind.url, poolclass=NullPool)
    try:
        async with async_sessionmaker(journal_engine, expire_on_commit=False)() as journal:
            await journal.execute(text("SET LOCAL synchronous_commit = on"))
            journal.add(row)
            await journal.commit()
    finally:
        await journal_engine.dispose()


class QuotaService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]):
        self.db, self.actor, self.context = db, actor, context

    async def admin(self) -> None:
        if not (
            await AuthorizationService().authorize(self.db, self.actor, "MANAGE_QUOTAS", None)
        ).allowed:
            raise HTTPException(403, "Quota administration required")

    async def dimensions(self, row: Resource) -> dict[str, uuid.UUID | None]:
        metadata = await self.db.get(DocumentMetadata, row.id)
        return {
            "USER": row.owner_user_id,
            "DEPARTMENT": row.department_id,
            "PROJECT": metadata.project_id if metadata else None,
        }

    async def department_scope(self, subject_id: uuid.UUID) -> set[uuid.UUID]:
        departments = (await self.db.scalars(select(Department))).all()
        ids = {subject_id}
        while True:
            children = {row.id for row in departments if row.parent_id in ids}
            if children <= ids:
                return ids
            ids |= children

    async def usage(self, kind: str, subject_id: uuid.UUID) -> int:
        column = {
            "USER": Resource.owner_user_id,
            "DEPARTMENT": Resource.department_id,
            "PROJECT": DocumentMetadata.project_id,
        }[kind]
        department_ids = await self.department_scope(subject_id) if kind == "DEPARTMENT" else set()
        scope_filter = column.in_(department_ids) if kind == "DEPARTMENT" else column == subject_id
        used = await self.db.scalar(
            select(func.coalesce(func.sum(DocumentVersion.size), 0))
            .select_from(DocumentVersion)
            .join(Resource, Resource.id == DocumentVersion.document_id)
            .outerjoin(DocumentMetadata, DocumentMetadata.document_id == Resource.id)
            .where(DocumentVersion.purged_at.is_(None), scope_filter)
        )
        reserved = 0
        rows = (
            await self.db.scalars(
                select(StorageReservation).where(
                    ~select(DocumentVersion.id)
                    .where(DocumentVersion.id == StorageReservation.version_id)
                    .exists()
                )
            )
        ).all()
        for row in rows:
            document = await self.db.get(Resource, row.document_id)
            dims = (
                await self.dimensions(document)
                if document
                else {
                    "USER": row.owner_id,
                    "DEPARTMENT": row.department_id,
                    "PROJECT": row.project_id,
                }
            )
            if (kind == "DEPARTMENT" and dims[kind] in department_ids) or (
                kind != "DEPARTMENT" and dims[kind] == subject_id
            ):
                reserved += row.size
        return int(used or 0) + reserved

    async def check(self, row: Resource, extra: int, kinds: set[str] | None = None) -> None:
        await governance_lock(self.db)
        dimensions = await self.dimensions(row)
        targets = list(dimensions.items())
        department = await self.db.get(Department, row.department_id)
        visited = {row.department_id}
        while department is not None and department.parent_id is not None:
            if department.parent_id in visited:
                raise ValueError("Invalid quota department hierarchy")
            visited.add(department.parent_id)
            targets.append(("DEPARTMENT", department.parent_id))
            department = await self.db.get(Department, department.parent_id)
        for kind, subject_id in targets:
            if subject_id is None or (kinds is not None and kind not in kinds):
                continue
            quota = await self.db.get(QuotaLimit, (kind, subject_id), populate_existing=True)
            if quota is None:
                continue
            used = await self.usage(kind, subject_id)
            if quota.limit_bytes == 0 or used + extra > quota.limit_bytes:
                await write_audit_event(
                    "quota_exceeded",
                    user=str(self.actor.id),
                    resource=str(row.id),
                    result="denied",
                    subject_type=kind,
                    subject_id=str(subject_id),
                    limit_bytes=quota.limit_bytes,
                    requested_bytes=extra,
                    **self.context,
                )
                await durable_record(
                    self.db,
                    QuotaIncident(
                        actor_id=self.actor.id,
                        resource_id=row.id,
                        subject_type=kind,
                        subject_id=subject_id,
                        limit_bytes=quota.limit_bytes,
                        requested_bytes=extra,
                    ),
                )
                raise HTTPException(413, "Storage quota exceeded")

    async def reserve(
        self,
        row: Resource,
        key: ObjectKey,
        source: BinaryIO,
        area: Area,
        source_resource_id: uuid.UUID | None = None,
    ) -> ObjectInfo:
        await governance_lock(self.db)
        info = await run_in_threadpool(fingerprint, source)
        await self.check(row, info.size)
        dimensions = await self.dimensions(row)
        ancestors = await chain(self.db, row.id)
        scopes = {str(item.id) for item in ancestors}
        if source_resource_id:
            scopes.update(str(item.id) for item in await chain(self.db, source_resource_id))
        reservation = StorageReservation(
            version_id=key.version_id,
            document_id=row.id,
            space_id=key.space_id,
            owner_id=row.owner_user_id,
            department_id=row.department_id,
            project_id=dimensions["PROJECT"],
            size=info.size,
            sha256=info.sha256,
            area=area.value,
            policy_scope_ids=sorted(scopes),
        )
        # Separate PG transaction survives rollback/crash of the resource/version transaction.
        # Caller already holds the shared accounting lock; this writer must not reacquire it.
        await durable_record(self.db, reservation)
        return info

    async def complete(self, version_id: uuid.UUID) -> None:
        # This deletion and the authoritative version commit are atomic.
        await self.db.execute(
            delete(StorageReservation).where(StorageReservation.version_id == version_id)
        )

    async def configure(
        self, kind: str, subject_id: uuid.UUID, limit: int, reason: str
    ) -> QuotaLimit:
        await self.admin()
        await governance_lock(self.db)
        model = {"USER": User, "DEPARTMENT": Department, "PROJECT": Project}.get(kind)
        if (
            model is None
            or limit < 0
            or not reason.strip()
            or await self.db.get(model, subject_id) is None
        ):
            raise ValueError("Invalid quota configuration")
        quota = await self.db.get(QuotaLimit, (kind, subject_id))
        old = quota.limit_bytes if quota else None
        if quota is None:
            quota = QuotaLimit(subject_type=kind, subject_id=subject_id, limit_bytes=limit)
            self.db.add(quota)
        else:
            quota.limit_bytes = limit
        await write_audit_event(
            "quota_changed",
            user=str(self.actor.id),
            resource=None,
            result="success",
            subject_type=kind,
            subject_id=str(subject_id),
            old_limit=old,
            new_limit=limit,
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return quota

    async def create_project(self, company_id: uuid.UUID, name: str) -> Project:
        await self.admin()
        company = await self.db.get(Company, company_id)
        if company is None or not company.enabled or not name.strip():
            raise ValueError("Invalid project company or name")
        project = Project(company_id=company_id, name=name)
        self.db.add(project)
        await self.db.flush()
        await write_audit_event(
            "project_created",
            user=str(self.actor.id),
            resource=None,
            result="success",
            project_id=str(project.id),
            company_id=str(company_id),
            **self.context,
        )
        await self.db.commit()
        return project

    async def validate_project(self, resource: Resource, project_id: uuid.UUID | None) -> None:
        if project_id is None:
            return
        project = await self.db.get(Project, project_id)
        department = await self.db.get(Department, resource.department_id)
        if (
            project is None
            or not project.enabled
            or department is None
            or project.company_id != department.company_id
        ):
            raise ValueError("Project unavailable for this document")
