from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.departments.service import OrganizationService
from app.governance.policy import governance_lock
from app.models.resource import Resource
from app.models.user import User


class ResourceService:
    """Metadata only. API caller must obtain AuthorizationService decisions first."""

    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]) -> None:
        self.db, self.actor, self.context = db, actor, context

    async def ancestors(self, resource_id: uuid.UUID) -> list[Resource]:
        rows: list[Resource] = []
        seen: set[uuid.UUID] = set()
        current: uuid.UUID | None = resource_id
        while current is not None:
            if current in seen:
                raise ValueError("Resource hierarchy cycle")
            seen.add(current)
            row = await self.db.get(Resource, current)
            if row is None:
                raise ValueError("Resource hierarchy incomplete")
            rows.append(row)
            current = row.parent_id
        for index, row in enumerate(rows):
            if row.resource_type not in {"SPACE", "FOLDER", "DOCUMENT"}:
                raise ValueError("Invalid resource type")
            if index > 0 and row.resource_type == "DOCUMENT":
                raise ValueError("Document cannot be a parent")
            if row.resource_type == "SPACE" and row.parent_id is not None:
                raise ValueError("Space cannot have a parent")
        if rows[-1].resource_type != "SPACE":
            raise ValueError("Resource has no space")
        return rows

    async def create(
        self,
        resource_type: str,
        name: str,
        department_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        inherit_acl: bool = True,
        classification: str = "INTERNAL",
    ) -> Resource:
        await governance_lock(self.db)
        if resource_type not in {"SPACE", "FOLDER", "DOCUMENT"}:
            raise ValueError("Invalid resource type")
        if classification not in {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"}:
            raise ValueError("Invalid classification")
        if not name.strip() or len(name) > 255:
            raise ValueError("Invalid resource name")
        if not self.actor.enabled:
            raise ValueError("User unavailable")
        dept = await OrganizationService(self.db, self.actor, self.context).department(
            department_id
        )
        if resource_type == "SPACE":
            if parent_id is not None:
                raise ValueError("Space cannot have a parent")
        else:
            parent = (
                await self.db.get(Resource, parent_id, with_for_update=True) if parent_id else None
            )
            if parent is None or parent.resource_type not in {"SPACE", "FOLDER"}:
                raise ValueError("Parent must be a space or folder")
            for ancestor in await self.ancestors(parent.id):
                if ancestor.state != "ACTIVE":
                    raise ValueError("Ancestor unavailable")
            parent_dept = await OrganizationService(self.db, self.actor, self.context).department(
                parent.department_id
            )
            if parent_dept.company_id != dept.company_id:
                raise ValueError("Resource cannot cross companies")
        row = Resource(
            resource_type=resource_type,
            name=name,
            parent_id=parent_id,
            owner_user_id=self.actor.id,
            department_id=department_id,
            inherit_acl=inherit_acl,
            classification=classification,
        )
        self.db.add(row)
        await self.db.flush()
        await write_audit_event(
            "resource_created",
            user=str(self.actor.id),
            resource=str(row.id),
            result="success",
            owner_user_id=str(row.owner_user_id),
            department_id=str(row.department_id),
            **self.context,
        )
        await self.db.commit()
        return row
