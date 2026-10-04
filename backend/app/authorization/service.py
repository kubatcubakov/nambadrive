from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization.catalog import BREAK_GLASS_PERMISSIONS, DEFAULTS, PERMISSIONS, SENSITIVE
from app.models.acl import ACLEntry, BreakGlassGrant, HardPolicy, Role, RoleBinding, RolePermission
from app.models.organization import (
    Company,
    Department,
    DepartmentManager,
    DepartmentMembership,
    OrganizationAdministrator,
)
from app.models.share import ExternalShare
from app.models.user import User
from app.resources.service import ResourceService


def utc(value: datetime) -> datetime:
    # SQLite test adapter omits offsets; production columns are timestamptz.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def active(
    row: RoleBinding | ACLEntry | DepartmentManager | BreakGlassGrant, now: datetime
) -> bool:
    return (
        row.revoked_at is None
        and utc(row.valid_from) <= now
        and (row.valid_until is None or now < utc(row.valid_until))
    )


@dataclass(frozen=True)
class AuthorizationDecision:
    decision: str
    permission: str
    reason: str
    resource_id: uuid.UUID | None
    source_resource_id: uuid.UUID | None = None
    principal_type: str | None = None
    principal_id: uuid.UUID | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


class AuthorizationService:
    async def organization_admin(self, db: AsyncSession, user: User) -> bool:
        stored = await db.scalar(select(User).where(User.id == user.id, User.enabled.is_(True)))
        return stored is not None and await db.get(OrganizationAdministrator, user.id) is not None

    async def system_admin(self, db: AsyncSession, user: User, now: datetime) -> bool:
        if not user.enabled:
            return False
        bindings = (
            await db.scalars(
                select(RoleBinding)
                .join(Role)
                .where(
                    RoleBinding.user_id == user.id,
                    RoleBinding.resource_id.is_(None),
                    Role.name == "SYSTEM_ADMIN",
                )
            )
        ).all()
        return any(active(binding, now) for binding in bindings)

    async def authorize(
        self,
        db: AsyncSession,
        user: User,
        permission: str,
        resource_id: uuid.UUID | None,
        *,
        session_valid: bool = True,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        now = now or datetime.now(UTC)

        def decision(
            allow: bool,
            reason: str,
            source: uuid.UUID | None = None,
            principal_type: str | None = None,
            principal_id: uuid.UUID | None = None,
        ) -> AuthorizationDecision:
            return AuthorizationDecision(
                "ALLOW" if allow else "DENY",
                permission,
                reason,
                resource_id,
                source,
                principal_type,
                principal_id,
            )

        if not session_valid or not user.enabled:
            return decision(False, "USER_INVALID")
        stored = await db.scalar(select(User).where(User.id == user.id, User.enabled.is_(True)))
        if stored is None:
            return decision(False, "USER_INVALID")
        if permission not in PERMISSIONS:
            return decision(False, "UNKNOWN_PERMISSION")
        if resource_id is None:
            global_policy = await db.scalar(
                select(HardPolicy).where(
                    HardPolicy.resource_id.is_(None), HardPolicy.permission_id == permission
                )
            )
            if global_policy is not None:
                return decision(False, "HARD_POLICY")
            if permission == "CREATE_SPACE" and await self.system_admin(db, user, now):
                return decision(True, "SYSTEM_ADMIN_CONFIGURATION")
            return decision(False, "RESOURCE_INVALID")
        try:
            chain = await ResourceService(db, user, {}).ancestors(resource_id)
        except ValueError:
            return decision(False, "RESOURCE_INVALID")
        resource = chain[0]
        if permission == "CREATE_SPACE":
            return decision(False, "INVALID_OPERATION")
        # Validate every ancestor; inheritance breaks only ordinary ACL/bindings.
        for row in chain:
            if row.state != "ACTIVE" and not (
                row is resource and row.state == "TRASH" and permission in {"PURGE", "RESTORE"}
            ):
                return decision(False, "RESOURCE_STATE", row.id)
            if (row.state == "TRASH") != (row.deleted_at is not None):
                return decision(False, "RESOURCE_STATE", row.id)
            dept = await db.get(Department, row.department_id)
            company = await db.get(Company, dept.company_id) if dept else None
            if dept is None or not dept.enabled or company is None or not company.enabled:
                return decision(False, "ORGANIZATION_DISABLED", row.id)
        # Validate department hierarchy before grants; manager scope includes its ancestors.
        department_ids: set[uuid.UUID] = set()
        current_dept: uuid.UUID | None = resource.department_id
        while current_dept is not None:
            if current_dept in department_ids:
                return decision(False, "ORGANIZATION_INVALID")
            department_ids.add(current_dept)
            dept = await db.get(Department, current_dept)
            if dept is None or not dept.enabled:
                return decision(False, "ORGANIZATION_DISABLED")
            current_dept = dept.parent_id
        ids = {row.id for row in chain}
        policies = (
            await db.scalars(select(HardPolicy).where(HardPolicy.permission_id == permission))
        ).all()
        for policy in policies:
            if policy.resource_id is None or policy.resource_id in ids:
                return decision(False, "HARD_POLICY", policy.resource_id)
        if permission == "EXTERNAL_SHARE" and any(row.classification != "PUBLIC" for row in chain):
            return decision(False, "CLASSIFICATION_HARD_POLICY")
        if permission == "PURGE":
            for row in chain:
                if row.legal_hold:
                    return decision(False, "LEGAL_HOLD", row.id)
                if row.retention_until and now < utc(row.retention_until):
                    return decision(False, "RETENTION", row.id)
            if resource.deleted_at is None or now < utc(resource.deleted_at) + timedelta(days=30):
                return decision(False, "TRASH_PERIOD")
        grants = (
            await db.scalars(
                select(BreakGlassGrant).where(
                    BreakGlassGrant.user_id == user.id,
                    BreakGlassGrant.permission_id == permission,
                    BreakGlassGrant.resource_id.in_(ids),
                )
            )
        ).all()
        for grant in grants:
            if (
                permission in BREAK_GLASS_PERMISSIONS
                and active(grant, now)
                and grant.audited
                and grant.reason.strip()
                and utc(grant.valid_until) - utc(grant.valid_from) <= timedelta(hours=1)
            ):
                return decision(True, "BREAK_GLASS", grant.resource_id, "USER", user.id)
        for row in chain:
            if row.owner_user_id == user.id:
                return decision(True, "OWNER", row.id, "USER", user.id)
        managers = (
            await db.scalars(
                select(DepartmentManager).where(
                    DepartmentManager.user_id == user.id,
                    DepartmentManager.department_id.in_(department_ids),
                )
            )
        ).all()
        if any(active(manager, now) for manager in managers):
            return decision(True, "DEPARTMENT_MANAGER", resource.id, "USER", user.id)
        scope: list[uuid.UUID] = []
        for row in chain:
            scope.append(row.id)
            if not row.inherit_acl:
                break
        bindings = [
            binding
            for binding in (
                await db.scalars(select(RoleBinding).where(RoleBinding.user_id == user.id))
            ).all()
            if active(binding, now)
            and (binding.resource_id is None or binding.resource_id in scope)
        ]
        role_ids = {binding.role_id for binding in bindings}
        # Administrative role labels never imply document permissions. Explicit ACL may grant them.
        memberships = (
            await db.scalars(
                select(DepartmentMembership).where(DepartmentMembership.user_id == user.id)
            )
        ).all()
        member_ids: set[uuid.UUID] = set()
        for membership in memberships:
            dept = await db.get(Department, membership.department_id)
            if dept and dept.enabled:
                company = await db.get(Company, dept.company_id)
                if company and company.enabled:
                    member_ids.add(dept.id)
        entries = (
            await db.scalars(
                select(ACLEntry).where(
                    ACLEntry.resource_id.in_(scope), ACLEntry.permission_id == permission
                )
            )
        ).all()
        applicable = [
            entry
            for entry in entries
            if active(entry, now)
            and (
                (entry.principal_type == "USER" and entry.principal_id == user.id)
                or (entry.principal_type == "DEPARTMENT" and entry.principal_id in member_ids)
                or (entry.principal_type == "ROLE" and entry.principal_id in role_ids)
            )
            and (
                (entry.resource_id == resource_id and entry.applies_to_self)
                or (entry.resource_id != resource_id and entry.propagate_to_children)
            )
        ]
        denies = [entry for entry in applicable if entry.effect == "DENY"]
        if denies:
            entry = sorted(denies, key=lambda e: str(e.id))[0]
            return decision(
                False, "ACL_DENY", entry.resource_id, entry.principal_type, entry.principal_id
            )
        allows = [entry for entry in applicable if entry.effect == "ALLOW"]
        if allows:
            entry = sorted(allows, key=lambda e: str(e.id))[0]
            return decision(
                True, "ACL_ALLOW", entry.resource_id, entry.principal_type, entry.principal_id
            )
        if any(row.classification == "STRICTLY_CONFIDENTIAL" for row in chain) and (
            permission in SENSITIVE or permission == "REQUEST_ACCESS_DISCOVERY"
        ):
            return decision(False, "CLASSIFICATION_REQUIRES_EXPLICIT_GRANT")
        role_permissions = (
            await db.scalars(
                select(RolePermission)
                .join(Role)
                .where(
                    RolePermission.role_id.in_(role_ids),
                    RolePermission.permission_id == permission,
                    Role.name.in_(["EDITOR", "REVIEWER", "READER"]),
                )
            )
        ).all()
        for role_permission in role_permissions:
            role = await db.get(Role, role_permission.role_id)
            if role is not None and permission in DEFAULTS.get(role.name, set()):
                return decision(True, "ROLE_DEFAULT", resource.id, "ROLE", role_permission.role_id)
        return decision(False, "DEFAULT_DENY")

    async def authorize_share(
        self,
        db: AsyncSession,
        share: ExternalShare,
        permission: str,
        *,
        password_valid: bool,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        now = now or datetime.now(UTC)

        def denied() -> AuthorizationDecision:
            return AuthorizationDecision("DENY", permission, "SHARE_INVALID", share.document_id)

        if (
            not password_valid
            or share.revoked_at is not None
            or utc(share.created_at) > now
            or now >= utc(share.expires_at)
            or utc(share.expires_at) - utc(share.created_at) > timedelta(days=30)
            or (share.max_views is not None and share.views >= share.max_views)
            or permission not in {"PREVIEW", "DOWNLOAD"}
            or (permission == "PREVIEW" and not share.allow_view)
            or (permission == "DOWNLOAD" and not share.allow_download)
        ):
            return denied()
        creator = await db.get(User, share.created_by, populate_existing=True)
        if creator is None:
            return denied()
        # Delegation never outlives the creator's current authorization or PUBLIC policy.
        for required in ("SHARE", "EXTERNAL_SHARE", "VIEW", permission):
            result = await self.authorize(db, creator, required, share.document_id, now=now)
            if not result.allowed:
                return denied()
        return AuthorizationDecision(
            "ALLOW", permission, "EXTERNAL_SHARE", share.document_id, share.document_id
        )

    async def authorize_discovery(
        self,
        db: AsyncSession,
        user: User,
        resource_id: uuid.UUID,
    ) -> AuthorizationDecision:
        # Discovery is an explicit, metadata-only ACL capability, never a default grant.
        result = await self.authorize(db, user, "REQUEST_ACCESS_DISCOVERY", resource_id)
        if not result.allowed:
            return result
        chain = await ResourceService(db, user, {}).ancestors(resource_id)
        if any(row.classification == "STRICTLY_CONFIDENTIAL" for row in chain):
            return AuthorizationDecision(
                "DENY", "REQUEST_ACCESS_DISCOVERY", "STRICT_DISCOVERY_HIDDEN", resource_id
            )
        return result

    async def authorize_request_approval(
        self,
        db: AsyncSession,
        user: User,
        resource_id: uuid.UUID,
    ) -> AuthorizationDecision:
        result = await self.authorize(db, user, "CHANGE_ACL", resource_id)
        if result.allowed and result.reason in {"OWNER", "DEPARTMENT_MANAGER"}:
            return result
        return AuthorizationDecision("DENY", "CHANGE_ACL", "OWNER_OR_MANAGER_REQUIRED", resource_id)
