from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.governance.policy import bind_retention, governance_lock, schedule_pruning, utc
from app.models.document import DocumentVersion
from app.models.governance import LegalHoldEvent, RetentionPolicy
from app.models.resource import Resource
from app.models.user import User


class GovernanceService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]):
        self.db, self.actor, self.context = db, actor, context

    async def require(self, permission: str) -> None:
        if not (
            await AuthorizationService().authorize(self.db, self.actor, permission, None)
        ).allowed:
            raise HTTPException(403, "Policy administration required")

    async def materialize(self) -> None:
        # Applying/revoking a policy never shortens a version's already bound retention deadline.
        versions = (
            await self.db.scalars(
                select(DocumentVersion).where(DocumentVersion.purged_at.is_(None))
            )
        ).all()
        document_ids = set()
        for version in versions:
            await bind_retention(self.db, version)
            document_ids.add(version.document_id)
        for resource_id in document_ids:
            await schedule_pruning(self.db, resource_id)
        await self.db.flush()

    async def create_policy(
        self,
        name: str,
        resource_id: uuid.UUID | None,
        document_type: str | None,
        days: int,
        reason: str,
    ) -> RetentionPolicy:
        await self.require("MANAGE_RETENTION")
        await governance_lock(self.db)
        if resource_id is not None and await self.db.get(Resource, resource_id) is None:
            raise ValueError("Policy scope unavailable")
        if not name.strip() or not reason.strip() or not 1 <= days <= 36500:
            raise ValueError("Invalid retention policy")
        if document_type is not None and document_type not in {
            "docx",
            "xlsx",
            "pptx",
            "pdf",
            "zip",
            "jpg",
            "png",
            "dwg",
            "psd",
            "txt",
            "csv",
            "json",
            "xml",
        }:
            raise ValueError("Unsupported policy document type")
        policy = RetentionPolicy(
            name=name,
            resource_id=resource_id,
            document_type=document_type,
            days=days,
            created_by=self.actor.id,
        )
        self.db.add(policy)
        await self.db.flush()
        await self.materialize()
        await write_audit_event(
            "retention_changed",
            user=str(self.actor.id),
            resource=str(resource_id) if resource_id else None,
            result="success",
            operation="create_policy",
            policy_id=str(policy.id),
            days=days,
            document_type=document_type,
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return policy

    async def revoke_policy(self, policy_id: uuid.UUID, reason: str) -> None:
        await self.require("MANAGE_RETENTION")
        await governance_lock(self.db)
        if not reason.strip():
            raise ValueError("Reason required")
        policy = await self.db.get(RetentionPolicy, policy_id, with_for_update=True)
        if policy is None:
            raise HTTPException(404, "Policy unavailable")
        policy.revoked_at, policy.revocation_reason = datetime.now(UTC), reason
        await write_audit_event(
            "retention_changed",
            user=str(self.actor.id),
            resource=str(policy.resource_id) if policy.resource_id else None,
            result="success",
            operation="revoke_policy",
            policy_id=str(policy.id),
            reason=reason,
            **self.context,
        )
        await self.db.commit()

    async def hold(self, resource_id: uuid.UUID, enabled: bool, reason: str) -> Resource:
        await self.require("MANAGE_LEGAL_HOLD")
        await governance_lock(self.db)
        row = await self.db.get(Resource, resource_id, with_for_update=True, populate_existing=True)
        if row is None or row.purged_at is not None:
            raise HTTPException(409, "Policy scope unavailable or already purged")
        if not reason.strip():
            raise ValueError("Reason required")
        old = row.legal_hold
        row.legal_hold = enabled
        self.db.add(
            LegalHoldEvent(
                resource_id=row.id, actor_id=self.actor.id, enabled=enabled, reason=reason
            )
        )
        await self.db.flush()
        await self.materialize()
        await write_audit_event(
            "legal_hold_enabled" if enabled else "legal_hold_disabled",
            user=str(self.actor.id),
            resource=str(row.id),
            result="success",
            old_value=old,
            new_value=enabled,
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return row

    async def extend(self, resource_id: uuid.UUID, until: datetime, reason: str) -> Resource:
        await self.require("MANAGE_RETENTION")
        await governance_lock(self.db)
        row = await self.db.get(Resource, resource_id, with_for_update=True, populate_existing=True)
        if row is None or row.purged_at is not None:
            raise HTTPException(409, "Policy scope unavailable or already purged")
        if (
            not reason.strip()
            or utc(until) <= datetime.now(UTC)
            or (row.retention_until and utc(until) < utc(row.retention_until))
        ):
            raise ValueError("Retention can only be extended to a future deadline")
        old = row.retention_until
        row.retention_until = until
        await self.db.flush()
        await self.materialize()
        await write_audit_event(
            "retention_changed",
            user=str(self.actor.id),
            resource=str(row.id),
            result="success",
            old_value=old.isoformat() if old else None,
            new_value=until.isoformat(),
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return row
