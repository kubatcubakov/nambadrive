from unittest.mock import AsyncMock, patch

import pytest

from app.departments.service import OrganizationService
from app.resources.service import ResourceService
from tests.test_organization import user


@pytest.mark.asyncio
async def test_tree_and_invalid_parents(db):
    actor = await user(db)
    with (
        patch("app.departments.service.write_audit_event", new=AsyncMock()),
        patch("app.resources.service.write_audit_event", new=AsyncMock()),
    ):
        org = OrganizationService(db, actor, {})
        company = await org.create_company("Company")
        department = await org.create_department(company.id, "D", None)
        svc = ResourceService(db, actor, {})
        space = await svc.create("SPACE", "Space", department.id)
        folder = await svc.create("FOLDER", "Folder", department.id, space.id, False)
        doc = await svc.create("DOCUMENT", "Document", department.id, folder.id)
        assert [r.id for r in await svc.ancestors(doc.id)] == [doc.id, folder.id, space.id]
        assert folder.inherit_acl is False
        assert doc.owner_user_id == actor.id
        with pytest.raises(ValueError, match="Parent"):
            await svc.create("FOLDER", "Invalid", department.id, doc.id)
        with pytest.raises(ValueError, match="parent"):
            await svc.create("SPACE", "Invalid", department.id, folder.id)
        other = await org.create_company("Other")
        other_dept = await org.create_department(other.id, "Other D", None)
        with pytest.raises(ValueError, match="cross companies"):
            await svc.create("DOCUMENT", "Invalid", other_dept.id, folder.id)
        with pytest.raises(ValueError, match="classification"):
            await svc.create("SPACE", "Invalid", department.id, classification="invalid")
        folder.parent_id = doc.id
        await db.flush()
        with pytest.raises(ValueError, match="cycle"):
            await svc.ancestors(doc.id)
