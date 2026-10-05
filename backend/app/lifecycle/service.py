"""Trusted identity synchronization, never a grant to document content."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService, active
from app.governance.policy import chain, governance_lock
from app.models.acl import ACLEntry, BreakGlassGrant, RoleBinding
from app.models.lifecycle import IdentityPolicy, OwnershipTransfer
from app.models.office import OfficeSession
from app.models.organization import (
    Company,
    Department,
    DepartmentManager,
    OrganizationAdministrator,
)
from app.models.resource import Resource
from app.models.session import ApplicationSession
from app.models.share import ExternalShare
from app.models.user import User


class LifecycleService:
    def __init__(self, db: AsyncSession, source: str):
        self.db, self.source = db, source

    async def audit(self, event: str, **fields: object) -> None:
        await write_audit_event(event, user=self.source, result="success", **fields)

    async def synchronize(
        self,
        external_id: str,
        username: str,
        display_name: str,
        email: str | None,
        enabled: bool,
        *,
        expected_id: uuid.UUID | None = None,
    ) -> User:
        await governance_lock(self.db)
        user = await self.db.scalar(
            select(User)
            .where(User.authentik_sub == external_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if expected_id is not None and (user is None or user.id != expected_id):
            raise HTTPException(409, "Immutable external identity mismatch")
        if user is None:
            user = User(
                authentik_sub=external_id,
                username=username,
                display_name=display_name,
                email=email,
                enabled=enabled,
            )
            self.db.add(user)
            await self.db.flush()
        user.username, user.display_name, user.email = username, display_name, email
        user.last_authentik_sync_at = datetime.now(UTC)
        if not enabled:
            await self.disable(user)
        elif not user.enabled:
            await self.transfer_pending()
            if await self.db.scalar(
                select(OwnershipTransfer.resource_id)
                .where(OwnershipTransfer.previous_owner_id == user.id)
                .limit(1)
            ):
                raise HTTPException(409, "Complete ownership transfer before re-enabling account")
            user.enabled = True
            await self.audit("user_enabled", subject_id=str(user.id), restored_grants=False)
        await self.audit("identity_synced", subject_id=str(user.id), enabled=enabled)
        await self.db.commit()
        return user

    async def disable(self, user: User) -> None:
        # Caller owns governance lock; re-runs also revoke grants assigned after a prior disable.
        user.enabled = False
        now = datetime.now(UTC)
        models = (
            (ApplicationSession, ApplicationSession.user_id == user.id),
            (OfficeSession, OfficeSession.user_id == user.id),
            (ExternalShare, ExternalShare.created_by == user.id),
            (ACLEntry, (ACLEntry.principal_type == "USER") & (ACLEntry.principal_id == user.id)),
            (RoleBinding, RoleBinding.user_id == user.id),
            (BreakGlassGrant, BreakGlassGrant.user_id == user.id),
            (DepartmentManager, DepartmentManager.user_id == user.id),
        )
        for model, predicate in models:
            rows = (
                await self.db.scalars(
                    select(model).where(predicate, model.revoked_at.is_(None)).with_for_update()
                )
            ).all()
            for row in rows:
                grant = cast(
                    ApplicationSession
                    | OfficeSession
                    | ExternalShare
                    | ACLEntry
                    | RoleBinding
                    | BreakGlassGrant
                    | DepartmentManager,
                    row,
                )
                old_acl = (
                    {c.name: str(getattr(grant, c.name)) for c in grant.__table__.columns}
                    if isinstance(grant, ACLEntry | RoleBinding | DepartmentManager)
                    else None
                )
                grant.revoked_at = now
                if old_acl is not None:
                    await self.audit(
                        "change_acl",
                        subject_id=str(user.id),
                        old_acl=old_acl,
                        new_acl={**old_acl, "revoked_at": now.isoformat()},
                        reason="disabled_user_lifecycle",
                    )
                identifier = getattr(row, "id", None) or getattr(row, "department_id", None)
                await self.audit(
                    "identity_grant_revoked",
                    subject_id=str(user.id),
                    grant_type=model.__tablename__,
                    grant_id=str(identifier),
                )
        org_admin = await self.db.get(OrganizationAdministrator, user.id)
        if org_admin:
            await self.db.delete(org_admin)
            await self.audit(
                "identity_grant_revoked",
                subject_id=str(user.id),
                grant_type="organization_administrator",
            )
        resources = (
            await self.db.scalars(
                select(Resource)
                .where(Resource.owner_user_id == user.id, Resource.purged_at.is_(None))
                .order_by(Resource.id)
                .with_for_update()
            )
        ).all()
        for resource in resources:
            pending = await self.db.get(OwnershipTransfer, resource.id)
            if pending is None:
                self.db.add(OwnershipTransfer(resource_id=resource.id, previous_owner_id=user.id))
        await self.db.flush()
        await self.transfer_pending()
        await self.audit("user_disabled", subject_id=str(user.id))

    async def successor(self, resource: Resource) -> tuple[User | None, str]:
        now = datetime.now(UTC)
        department_id: uuid.UUID | None = resource.department_id
        seen: set[uuid.UUID] = set()
        while department_id is not None:
            if department_id in seen:
                raise ValueError("Invalid department hierarchy")
            seen.add(department_id)
            department = await self.db.get(Department, department_id, populate_existing=True)
            company = await self.db.get(Company, department.company_id) if department else None
            if not department or not department.enabled or not company or not company.enabled:
                break
            managers = (
                await self.db.execute(
                    select(DepartmentManager, User)
                    .join(User)
                    .where(DepartmentManager.department_id == department_id, User.enabled.is_(True))
                    .order_by(User.id)
                )
            ).all()
            for manager, candidate in managers:
                if active(manager, now) and candidate.id != resource.owner_user_id:
                    return candidate, "DEPARTMENT_OWNER"
            department_id = department.parent_id
        root = (await chain(self.db, resource.id))[-1]
        owner = await self.db.get(User, root.owner_user_id, populate_existing=True)
        if owner and owner.enabled and owner.id != resource.owner_user_id:
            return owner, "SPACE_OWNER"
        policy = await self.db.get(IdentityPolicy, "GLOBAL")
        owner = (
            await self.db.get(User, policy.global_owner_id, populate_existing=True)
            if policy
            else None
        )
        return (
            owner if owner and owner.enabled and owner.id != resource.owner_user_id else None
        ), "GLOBAL_DOCUMENT_OWNER"

    async def transfer_pending(self) -> int:
        await governance_lock(self.db)
        count = 0
        pending = (
            await self.db.scalars(
                select(OwnershipTransfer).order_by(OwnershipTransfer.resource_id).with_for_update()
            )
        ).all()
        for task in pending:
            resource = await self.db.get(Resource, task.resource_id, populate_existing=True)
            if (
                resource is None
                or resource.purged_at is not None
                or resource.owner_user_id != task.previous_owner_id
            ):
                await self.db.delete(task)
                continue
            owner, source = await self.successor(resource)
            if owner is None:
                continue
            previous = resource.owner_user_id
            resource.owner_user_id = owner.id
            await self.audit(
                "ownership_changed",
                resource=str(resource.id),
                previous_owner_id=str(previous),
                new_owner_id=str(owner.id),
                fallback=source,
                reason="disabled_user_lifecycle",
            )
            await self.db.delete(task)
            count += 1
        return count

    async def configure(self, actor: User, owner_id: uuid.UUID, reason: str) -> None:
        await governance_lock(self.db)
        if not (
            await AuthorizationService().authorize(self.db, actor, "MANAGE_IDENTITY", None)
        ).allowed:
            raise HTTPException(403, "Access denied")
        owner = await self.db.get(User, owner_id, populate_existing=True)
        if owner is None or not owner.enabled or not reason.strip():
            raise ValueError("Enabled global owner and reason required")
        policy = await self.db.get(IdentityPolicy, "GLOBAL")
        previous = str(policy.global_owner_id) if policy else None
        if policy:
            policy.global_owner_id = owner_id
        else:
            self.db.add(IdentityPolicy(id="GLOBAL", global_owner_id=owner_id))
        await self.audit(
            "identity_policy_changed",
            previous_owner_id=previous,
            new_owner_id=str(owner_id),
            reason=reason,
        )
        await self.db.flush()
        await self.transfer_pending()
        await self.db.commit()
