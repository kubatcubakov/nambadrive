from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.governance.policy import governance_lock
from app.models.document import DocumentVersion
from app.models.drive import Favorite, RecentDocument
from app.models.organization import Department, DepartmentMembership
from app.models.resource import Resource
from app.models.user import User


class DriveService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]):
        self.db, self.actor, self.context = db, actor, context
        self.authorization = AuthorizationService()

    async def own(self) -> None:
        if not await self.authorization.account_self(self.db, self.actor, self.actor.id):
            raise HTTPException(403, "Access denied")

    async def listing(
        self, view: str, department_id: uuid.UUID | None = None, page: int = 1
    ) -> list[dict]:
        await self.own()
        query = select(Resource).where(Resource.purged_at.is_(None))
        if view == "spaces":
            query = query.where(Resource.resource_type == "SPACE")
        elif view in {"recent", "favorites"}:
            model = RecentDocument if view == "recent" else Favorite
            query = query.join(model, model.resource_id == Resource.id).where(
                model.user_id == self.actor.id
            )
        else:
            query = query.where(Resource.resource_type == "DOCUMENT")
        if view == "mine":
            query = query.where(Resource.owner_user_id == self.actor.id)
        if view == "shared":
            query = query.where(Resource.owner_user_id != self.actor.id)
        if view == "departments":
            memberships = select(DepartmentMembership.department_id).where(
                DepartmentMembership.user_id == self.actor.id
            )
            query = (
                query.where(Resource.department_id == department_id)
                if department_id
                else query.where(Resource.department_id.in_(memberships))
            )
        query = query.where(Resource.state == ("TRASH" if view == "trash" else "ACTIVE"))
        query = (
            query.order_by(RecentDocument.viewed_at.desc())
            if view == "recent"
            else query.order_by(Resource.name, Resource.id)
        )
        result: list[dict] = []
        # Scan in bounded DB batches. Limit only visible results; no hidden total/cursor exposed.
        offset = 0
        visible_seen = 0
        visible_skip = (page - 1) * 100
        while len(result) < 100:
            rows = (
                await self.db.scalars(
                    query.offset(offset).limit(200).execution_options(populate_existing=True)
                )
            ).all()
            if not rows:
                break
            for resource in rows:
                permission = "RESTORE" if view == "trash" else "VIEW"
                if not (
                    await self.authorization.authorize(self.db, self.actor, permission, resource.id)
                ).allowed:
                    continue
                version = (
                    await self.db.scalar(
                        select(DocumentVersion).where(
                            DocumentVersion.document_id == resource.id,
                            DocumentVersion.is_current.is_(True),
                            DocumentVersion.purged_at.is_(None),
                        )
                    )
                    if resource.resource_type == "DOCUMENT"
                    else None
                )
                if view != "trash" and resource.resource_type == "DOCUMENT" and version is None:
                    continue
                visible_seen += 1
                if visible_seen <= visible_skip:
                    continue
                owner = await self.db.get(User, resource.owner_user_id)
                department = await self.db.get(Department, resource.department_id)
                favorite = await self.db.get(Favorite, (self.actor.id, resource.id))
                result.append(
                    {
                        "id": resource.id,
                        "name": resource.name,
                        "resource_type": resource.resource_type,
                        "department_id": resource.department_id,
                        "department_name": department.name if department else None,
                        "owner_user_id": resource.owner_user_id,
                        "owner_name": owner.display_name if owner else None,
                        "classification": resource.classification,
                        "size": version.size if version else None,
                        "favorite": favorite is not None,
                    }
                )
                if len(result) == 100:
                    break
            offset += len(rows)
        return result

    async def favorite(self, resource_id: uuid.UUID, enabled: bool) -> None:
        await governance_lock(self.db)
        await self.own()
        row = await self.db.get(Favorite, (self.actor.id, resource_id))
        if enabled:
            if not (
                await self.authorization.authorize(self.db, self.actor, "VIEW", resource_id)
            ).allowed:
                raise HTTPException(403, "Access denied")
            if row is None:
                self.db.add(Favorite(user_id=self.actor.id, resource_id=resource_id))
        elif row is not None:
            await self.db.delete(row)
        await write_audit_event(
            "favorite_changed",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            enabled=enabled,
            **self.context,
        )
        await self.db.commit()

    async def viewed(self, resource_id: uuid.UUID) -> None:
        row = await self.db.get(RecentDocument, (self.actor.id, resource_id))
        if row is None:
            row = RecentDocument(user_id=self.actor.id, resource_id=resource_id)
            self.db.add(row)
        row.viewed_at = datetime.now(UTC)
