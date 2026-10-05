from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentVersion
from app.models.governance import RetentionPolicy
from app.models.resource import Resource


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def governance_lock(db: AsyncSession) -> None:
    # Same lock as the PostgreSQL hierarchy trigger: a hold/move cannot race physical cleanup.
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(735904)"))


async def chain(db: AsyncSession, resource_id: uuid.UUID) -> list[Resource]:
    result: list[Resource] = []
    seen = set()
    current: uuid.UUID | None = resource_id
    while current is not None:
        if current in seen:
            raise ValueError("Invalid policy hierarchy")
        seen.add(current)
        row = await db.get(Resource, current, populate_existing=True)
        if row is None:
            raise ValueError("Invalid policy hierarchy")
        result.append(row)
        current = row.parent_id
    if not result or result[-1].resource_type != "SPACE":
        raise ValueError("Invalid policy hierarchy")
    return result


async def deadline(
    db: AsyncSession, version: DocumentVersion, ancestors: list[Resource]
) -> datetime | None:
    values = [utc(row.retention_until) for row in ancestors if row.retention_until]
    if version.retention_until:
        values.append(utc(version.retention_until))
    ids = {row.id for row in ancestors}
    policies = (
        await db.scalars(select(RetentionPolicy).where(RetentionPolicy.revoked_at.is_(None)))
    ).all()
    for policy in policies:
        if policy.resource_id is not None and policy.resource_id not in ids:
            continue
        if (
            policy.document_type
            and policy.document_type != version.filename.rsplit(".", 1)[-1].lower()
        ):
            continue
        values.append(utc(version.created_at) + timedelta(days=policy.days))
    return max(values) if values else None


async def bind_retention(db: AsyncSession, version: DocumentVersion) -> None:
    await governance_lock(db)
    ancestors = await chain(db, version.document_id)
    version.retention_until = await deadline(db, version, ancestors)


async def schedule_pruning(db: AsyncSession, resource_id: uuid.UUID) -> None:
    ancestors = await chain(db, resource_id)
    held = any(row.legal_hold for row in ancestors)
    now = datetime.now(UTC)
    versions = (
        await db.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == resource_id,
                DocumentVersion.status == "CLEAN",
                DocumentVersion.purged_at.is_(None),
            )
            .order_by(DocumentVersion.sequence_no.desc())
        )
    ).all()
    for index, version in enumerate(versions):
        expiry = await deadline(db, version, ancestors)
        if index < 3 or held or (expiry is not None and expiry > now):
            version.prune_after = None
        elif version.prune_after is None:
            version.prune_after = now + timedelta(days=30)
