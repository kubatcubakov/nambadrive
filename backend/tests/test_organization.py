import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.dependencies import current_user
from app.authorization.service import AuthorizationService
from app.core.database import get_db
from app.departments.service import OrganizationService
from app.main import app
from app.models.organization import (
    DepartmentManager,
    DepartmentMembership,
    OrganizationAdministrator,
)
from app.models.user import User


async def user(db):
    row = User(authentik_sub=str(uuid.uuid4()), username="test", display_name="Test")
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_org_structure_memberships_managers(db):
    actor = await user(db)
    with patch("app.departments.service.write_audit_event", new=AsyncMock()) as audit:
        svc = OrganizationService(db, actor, {})
        company = await svc.create_company("Company")
        parent = await svc.create_department(company.id, "Department", None)
        child = await svc.create_department(company.id, "Section", parent.id)
        await svc.assign(parent.id, actor.id, "PRIMARY")
        await svc.assign(child.id, actor.id, "SECONDARY")
        with pytest.raises(ValueError, match="primary"):
            await svc.assign(child.id, actor.id, "PRIMARY")
        await svc.assign(parent.id, actor.id, "MANAGER", datetime.now(UTC) + timedelta(days=1))
        second = await user(db)
        await svc.assign(parent.id, second.id, "MANAGER")
        assert len((await db.scalars(select(DepartmentManager))).all()) == 2
        assert len((await db.scalars(select(DepartmentMembership))).all()) == 2
        await svc.revoke_manager(parent.id, actor.id)
        assert (await db.get(DepartmentManager, (actor.id, parent.id))).revoked_at
        assert audit.await_count == 8


@pytest.mark.asyncio
async def test_cross_company_disabled_and_expired_assignments(db):
    actor = await user(db)
    with patch("app.departments.service.write_audit_event", new=AsyncMock()):
        svc = OrganizationService(db, actor, {})
        a, b = await svc.create_company("A"), await svc.create_company("B")
        dept = await svc.create_department(a.id, "Department", None)
        with pytest.raises(ValueError, match="another company"):
            await svc.create_department(b.id, "Section", dept.id)
        with pytest.raises(ValueError, match="future"):
            await svc.assign(dept.id, actor.id, "MANAGER", datetime.now(UTC) - timedelta(seconds=1))
        actor.enabled = False
        await db.commit()
        with pytest.raises(ValueError, match="User unavailable"):
            await svc.assign(dept.id, actor.id, "SECONDARY")


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_manager(db):
    actor = await user(db)
    with patch("app.departments.service.write_audit_event", new=AsyncMock()):
        svc = OrganizationService(db, actor, {})
        company = await svc.create_company("A")
        dept = await svc.create_department(company.id, "D", None)
    uid, did = actor.id, dept.id
    with patch("app.departments.service.write_audit_event", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            await svc.assign(did, uid, "MANAGER")
    await db.rollback()
    assert await db.get(DepartmentManager, (uid, did)) is None


@pytest.mark.asyncio
async def test_admin_api_denies_unprivileged_and_requires_csrf(db):
    actor = await user(db)

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[current_user] = lambda: actor
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/v1/admin/organization")).status_code == 403
            db.add(OrganizationAdministrator(user_id=actor.id))
            await db.commit()
            assert (await client.get("/api/v1/admin/organization")).status_code == 200
            assert (
                await client.post("/api/v1/admin/organization/companies", json={"name": "X"})
            ).status_code == 403
            actor.enabled = False
            assert not await AuthorizationService().organization_admin(db, actor)
    finally:
        app.dependency_overrides.clear()
