from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.catalog import BREAK_GLASS_PERMISSIONS, PERMISSIONS
from app.authorization.service import AuthorizationService
from app.models.acl import ACLEntry, BreakGlassGrant, Role, RoleBinding
from app.models.organization import Department
from app.models.resource import Resource
from app.models.user import User


class ACLAdministrationService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]) -> None:
        self.db, self.actor, self.context = db, actor, context
        self.authz = AuthorizationService()

    async def require(self, resource_id: uuid.UUID) -> None:
        await self.db.get(Resource, resource_id, with_for_update=True)
        result = await self.authz.authorize(self.db, self.actor, "CHANGE_ACL", resource_id)
        if not result.allowed:
            raise HTTPException(403, "Access denied")

    async def list_entries(self, resource_id: uuid.UUID) -> list[ACLEntry]:
        await self.require(resource_id)
        return list(
            (
                await self.db.scalars(select(ACLEntry).where(ACLEntry.resource_id == resource_id))
            ).all()
        )

    async def grant(
        self,
        resource_id: uuid.UUID,
        principal_type: str,
        principal_id: uuid.UUID,
        permission: str,
        effect: str,
        applies_to_self: bool,
        propagate_to_children: bool,
        reason: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        *,
        commit: bool = True,
    ) -> ACLEntry:
        await self.require(resource_id)
        now = datetime.now(UTC)
        valid_from = valid_from or now
        if (
            permission
            not in PERMISSIONS
            - {"CREATE_SPACE", "PURGE", "MANAGE_RETENTION", "MANAGE_LEGAL_HOLD", "MANAGE_QUOTAS"}
            or effect not in {"ALLOW", "DENY"}
            or not reason.strip()
            or not (applies_to_self or propagate_to_children)
            or (valid_until is not None and valid_until <= valid_from)
        ):
            raise ValueError("Invalid ACL grant")
        model = {"USER": User, "DEPARTMENT": Department, "ROLE": Role}.get(principal_type)
        if model is None:
            raise ValueError("Invalid principal")
        principal = await self.db.get(model, principal_id)
        if principal is None or (
            isinstance(principal, User | Department) and not principal.enabled
        ):
            raise ValueError("Principal unavailable")
        entry = ACLEntry(
            resource_id=resource_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission_id=permission,
            effect=effect,
            applies_to_self=applies_to_self,
            propagate_to_children=propagate_to_children,
            reason=reason,
            valid_from=valid_from,
            valid_until=valid_until,
            created_by=self.actor.id,
            source="EXPLICIT",
        )
        self.db.add(entry)
        await self.db.flush()
        await write_audit_event(
            "change_acl",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            old_acl=None,
            new_acl=self.record(entry),
            **self.context,
        )
        if commit:
            await self.db.commit()
        return entry

    @staticmethod
    def record(entry: ACLEntry) -> dict[str, str]:
        return {column.name: str(getattr(entry, column.name)) for column in entry.__table__.columns}

    async def revoke(self, resource_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        await self.require(resource_id)
        entry = await self.db.get(ACLEntry, entry_id, with_for_update=True)
        if entry is None or entry.resource_id != resource_id:
            raise HTTPException(404, "ACL entry unavailable")
        old = self.record(entry)
        entry.revoked_at = datetime.now(UTC)
        await self.db.flush()
        await write_audit_event(
            "change_acl",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            old_acl=old,
            new_acl=self.record(entry),
            **self.context,
        )
        await self.db.commit()

    async def break_glass(
        self, resource_id: uuid.UUID, permission: str, reason: str, minutes: int
    ) -> BreakGlassGrant:
        now = datetime.now(UTC)
        decision = await self.authz.authorize(self.db, self.actor, "CREATE_SPACE", None, now=now)
        if not decision.allowed:
            raise HTTPException(403, "System administration required")
        if (
            permission not in BREAK_GLASS_PERMISSIONS
            or not reason.strip()
            or not 1 <= minutes <= 60
        ):
            raise ValueError("Invalid emergency grant")
        if await self.db.get(Resource, resource_id) is None:
            raise HTTPException(404, "Resource unavailable")
        grant = BreakGlassGrant(
            user_id=self.actor.id,
            resource_id=resource_id,
            permission_id=permission,
            reason=reason,
            created_by=self.actor.id,
            valid_from=now,
            valid_until=now + timedelta(minutes=minutes),
            audited=True,
        )
        self.db.add(grant)
        await self.db.flush()
        await write_audit_event(
            "admin_breakglass",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            grant=str(grant.id),
            permission=permission,
            reason=reason,
            valid_until=grant.valid_until.isoformat(),
            **self.context,
        )
        await self.db.commit()
        return grant

    async def bind_role(
        self,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        role_name: str,
        valid_until: datetime | None = None,
    ) -> RoleBinding:
        await self.require(resource_id)
        now = datetime.now(UTC)
        if role_name not in {"EDITOR", "REVIEWER", "READER", "GUEST"}:
            raise ValueError("Role is not assignable through resource ACL administration")
        if valid_until is not None and valid_until <= now:
            raise ValueError("Role expiry must be in the future")
        subject = await self.db.get(User, user_id)
        role = await self.db.scalar(select(Role).where(Role.name == role_name))
        if subject is None or not subject.enabled or role is None:
            raise ValueError("Role subject unavailable")
        binding = RoleBinding(
            user_id=user_id,
            role_id=role.id,
            resource_id=resource_id,
            valid_from=now,
            valid_until=valid_until,
        )
        self.db.add(binding)
        await self.db.flush()
        new = {
            column.name: str(getattr(binding, column.name)) for column in binding.__table__.columns
        }
        await write_audit_event(
            "change_acl",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            old_acl=None,
            new_acl=new,
            **self.context,
        )
        await self.db.commit()
        return binding

    async def revoke_binding(self, resource_id: uuid.UUID, binding_id: uuid.UUID) -> None:
        await self.require(resource_id)
        binding = await self.db.get(RoleBinding, binding_id, with_for_update=True)
        if binding is None or binding.resource_id != resource_id:
            raise HTTPException(404, "Role binding unavailable")
        old = {
            column.name: str(getattr(binding, column.name)) for column in binding.__table__.columns
        }
        binding.revoked_at = datetime.now(UTC)
        await self.db.flush()
        new = {
            column.name: str(getattr(binding, column.name)) for column in binding.__table__.columns
        }
        await write_audit_event(
            "change_acl",
            user=str(self.actor.id),
            resource=str(resource_id),
            result="success",
            old_acl=old,
            new_acl=new,
            **self.context,
        )
        await self.db.commit()
