from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.models.organization import Company, Department, DepartmentManager, DepartmentMembership
from app.models.user import User


class OrganizationService:
    def __init__(self, db: AsyncSession, actor: User, context: dict[str, Any]) -> None:
        self.db, self.actor, self.context = db, actor, context

    async def department(self, department_id: uuid.UUID) -> Department:
        department = await self.db.get(Department, department_id)
        if department is None or not department.enabled:
            raise ValueError("Department unavailable")
        company = await self.db.get(Company, department.company_id)
        if company is None or not company.enabled:
            raise ValueError("Company unavailable")
        return department

    async def save(
        self,
        obj: Company | Department | DepartmentMembership | DepartmentManager,
        event: str,
        old: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(obj)
        await self.db.flush()
        await write_audit_event(
            event,
            user=str(self.actor.id),
            result="success",
            old=old,
            new={c.name: str(getattr(obj, c.name)) for c in obj.__table__.columns},
            **self.context,
        )
        await self.db.commit()

    async def create_company(self, name: str) -> Company:
        company = Company(name=name)
        await self.save(company, "company_created")
        return company

    async def create_department(
        self, company_id: uuid.UUID, name: str, parent_id: uuid.UUID | None
    ) -> Department:
        company = await self.db.get(Company, company_id)
        if company is None or not company.enabled:
            raise ValueError("Company unavailable")
        if parent_id is not None and (await self.department(parent_id)).company_id != company_id:
            raise ValueError("Parent belongs to another company")
        department = Department(company_id=company_id, name=name, parent_id=parent_id)
        await self.save(department, "department_created")
        return department

    async def assign(
        self,
        department_id: uuid.UUID,
        user_id: uuid.UUID,
        kind: str,
        valid_until: datetime | None = None,
    ) -> None:
        await self.department(department_id)
        # Serialize assignments for a user, including primary membership changes.
        user = await self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or not user.enabled:
            raise ValueError("User unavailable")
        now = datetime.now(UTC)
        if kind == "MANAGER":
            if valid_until is not None and valid_until <= now:
                raise ValueError("Manager expiry must be in the future")
            manager = await self.db.get(DepartmentManager, (user_id, department_id))
            old = (
                {"valid_until": str(manager.valid_until), "revoked_at": str(manager.revoked_at)}
                if manager
                else None
            )
            if manager is None:
                manager = DepartmentManager(user_id=user_id, department_id=department_id)
            manager.valid_from, manager.valid_until, manager.revoked_at = now, valid_until, None
            await self.save(manager, "department_manager_changed", old)
        else:
            if kind == "PRIMARY":
                primary = await self.db.scalar(
                    select(DepartmentMembership).where(
                        DepartmentMembership.user_id == user_id,
                        DepartmentMembership.kind == "PRIMARY",
                        DepartmentMembership.department_id != department_id,
                    )
                )
                if primary is not None:
                    raise ValueError("User already has a primary department")
            membership = await self.db.get(DepartmentMembership, (user_id, department_id))
            if membership is None:
                membership = DepartmentMembership(user_id=user_id, department_id=department_id)
            old = {"kind": membership.kind}
            membership.kind = kind
            await self.save(membership, "department_membership_changed", old)

    async def revoke_manager(self, department_id: uuid.UUID, user_id: uuid.UUID) -> None:
        manager = await self.db.get(
            DepartmentManager, (user_id, department_id), with_for_update=True
        )
        if manager is None:
            raise ValueError("Manager not found")
        old = {"revoked_at": str(manager.revoked_at)}
        manager.revoked_at = datetime.now(UTC)
        await self.save(manager, "department_manager_changed", old)
