from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.administration import ACLAdministrationService
from app.authorization.service import AuthorizationService, utc
from app.models.access_request import AccessRequest
from app.models.resource import Resource
from app.models.user import User


class AccessRequestService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]):
        self.db, self.actor, self.context = db, actor, context
        self.authorization = AuthorizationService()

    async def visible(self, resource_id: uuid.UUID) -> bool:
        if (await self.authorization.authorize(self.db, self.actor, "VIEW", resource_id)).allowed:
            return True
        return (
            await self.authorization.authorize_discovery(self.db, self.actor, resource_id)
        ).allowed

    async def create(
        self, resource_id: uuid.UUID, permission: str, reason: str, until: datetime | None
    ) -> AccessRequest:
        row = await self.db.get(Resource, resource_id, with_for_update=True)
        if not await self.visible(resource_id):
            raise HTTPException(403, "Access request unavailable")
        if row is None or row.resource_type != "DOCUMENT":
            raise ValueError("Document required")
        if permission not in {"VIEW", "EDIT", "DOWNLOAD"} or not reason.strip():
            raise ValueError("Invalid access request")
        if until is not None and utc(until) <= datetime.now(UTC):
            raise ValueError("Access expiry must be in the future")
        request = AccessRequest(
            resource_id=resource_id,
            requested_by=self.actor.id,
            permission_id=permission,
            reason=reason,
            requested_until=until,
        )
        self.db.add(request)
        await self.db.flush()
        await write_audit_event(
            "access_request",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            request_id=str(request.id),
            permission=permission,
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return request

    async def list_requests(self, inbox: bool) -> list[dict[str, Any]]:
        query = select(AccessRequest).order_by(AccessRequest.created_at.desc())
        if inbox:
            query = query.where(AccessRequest.status == "PENDING")
        else:
            query = query.where(AccessRequest.requested_by == self.actor.id)
        rows = (await self.db.scalars(query)).all()
        results = []
        for request in rows:
            if inbox:
                allowed = (
                    await self.authorization.authorize_request_approval(
                        self.db, self.actor, request.resource_id
                    )
                ).allowed
            else:
                allowed = await self.visible(request.resource_id)
            if allowed:
                resource = await self.db.get(Resource, request.resource_id)
                results.append({**self.record(request), "name": resource.name if resource else ""})
        return results

    async def decide(
        self, request_id: uuid.UUID, approve: bool, reason: str, until: datetime | None
    ) -> AccessRequest:
        request = await self.db.get(AccessRequest, request_id)
        if request is None:
            raise HTTPException(403, "Access request unavailable")
        await self.db.get(Resource, request.resource_id, with_for_update=True)
        await self.db.refresh(request, with_for_update=True)
        if not (
            await self.authorization.authorize_request_approval(
                self.db, self.actor, request.resource_id
            )
        ).allowed:
            raise HTTPException(403, "Owner or department manager approval required")
        if request.status != "PENDING":
            raise HTTPException(409, "Access request already decided")
        if not reason.strip():
            raise ValueError("Decision reason required")
        now = datetime.now(UTC)
        if approve:
            subject = await self.db.get(User, request.requested_by, populate_existing=True)
            if subject is None or not subject.enabled:
                raise ValueError("Requester unavailable")
            # Approver may shorten, never silently lengthen, the requested temporary grant.
            dates = [utc(value) for value in [until, request.requested_until] if value is not None]
            expiry = min(dates) if dates else None
            if expiry is not None and expiry <= now:
                raise ValueError("Access request expired")
            entry = await ACLAdministrationService(self.db, self.actor, self.context).grant(
                request.resource_id,
                "USER",
                request.requested_by,
                request.permission_id,
                "ALLOW",
                True,
                False,
                "Access request: " + reason,
                now,
                expiry,
                commit=False,
            )
            request.acl_entry_id = entry.id
        request.status = "APPROVED" if approve else "DENIED"
        request.decided_by, request.decided_at, request.decision_reason = self.actor.id, now, reason
        await self.db.flush()
        await write_audit_event(
            "access_approved" if approve else "access_denied",
            user=str(self.actor.id),
            resource=str(request.resource_id),
            result="success",
            request_id=str(request.id),
            requester=str(request.requested_by),
            permission=request.permission_id,
            reason=reason,
            **self.context,
        )
        await self.db.commit()
        return request

    @staticmethod
    def record(row: AccessRequest) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    async def discover(self, query: str, limit: int) -> list[dict[str, Any]]:
        # Filename-only DB query: inaccessible document content never participates.
        rows = (
            await self.db.scalars(
                select(Resource)
                .where(
                    Resource.resource_type == "DOCUMENT",
                    Resource.state == "ACTIVE",
                    Resource.name.icontains(query, autoescape=True),
                )
                .order_by(Resource.id)
                .limit(1000)
            )
        ).all()
        results = []
        for row in rows:
            if (await self.authorization.authorize_discovery(self.db, self.actor, row.id)).allowed:
                results.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "type": row.name.rsplit(".", 1)[-1].lower(),
                        "owner_id": row.owner_user_id,
                        "department_id": row.department_id,
                    }
                )
                if len(results) >= limit:
                    break
        return results
