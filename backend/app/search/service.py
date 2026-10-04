from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.models.user import User
from app.search.clients import OpenSearch


async def search(
    db: AsyncSession,
    actor: User,
    index: OpenSearch,
    query: str,
    limit: int,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = await run_in_threadpool(index.candidates, query)
    visible: list[dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        if candidate.document_id in seen:
            continue
        seen.add(candidate.document_id)
        # Engine data is derived, untrusted and potentially stale. Always use current DB state.
        row = await db.get(Resource, candidate.document_id, populate_existing=True)
        if row is None or row.resource_type != "DOCUMENT":
            continue
        version = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == candidate.version_id,
                DocumentVersion.document_id == row.id,
                DocumentVersion.status == "CLEAN",
                DocumentVersion.is_current.is_(True),
            )
        )
        if version is None:
            continue
        authorization = AuthorizationService()
        if not (await authorization.authorize(db, actor, "VIEW", row.id)).allowed:
            continue
        preview = (await authorization.authorize(db, actor, "PREVIEW", row.id)).allowed
        # Content-only matches themselves disclose content, even without a snippet.
        if not preview and not candidate.name_match:
            continue
        visible.append(
            {
                "id": row.id,
                "name": row.name,
                "resource_type": "DOCUMENT",
                "department_id": row.department_id,
                "snippet": candidate.snippet if preview else "",
            }
        )
        await write_audit_event(
            "view",
            user=str(actor.id),
            resource=str(row.id),
            result="success",
            operation="search",
            **context,
        )
        if len(visible) >= limit:
            break
    # No total/count/score/aggregations/opaque engine IDs or unrestricted query text in audit.
    return visible
