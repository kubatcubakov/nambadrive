from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import current_user, require_csrf
from app.core.database import get_db
from app.main import app
from tests.test_authorization import acl, binding
from tests.test_authorization import scene as authorization_scene

scene = authorization_scene


@pytest.fixture
async def api(db, scene):
    state = {"actor": scene[1]}

    async def session():
        try:
            yield db
        except Exception:
            await db.rollback()
            for row in scene:
                await db.refresh(row)
            raise

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[current_user] = lambda: state["actor"]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


async def test_resource_routes_deny_idor_and_filter_lists(api, db, scene):
    client, _ = api
    _, _, space, folder, doc, _, _ = scene
    for path in (f"/{doc.id}", f"/{doc.id}/acl", f"/{doc.id}/permissions/DOWNLOAD"):
        response = await client.get("/api/v1/resources" + path)
        assert response.status_code == 403
        assert response.json()["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
        assert str(doc.id) not in response.text
    assert (await client.get("/api/v1/resources")).json()["data"] == []
    assert (await client.get(f"/api/v1/resources?parent_id={folder.id}")).json()["data"] == []
    await acl(db, scene, valid_from=datetime.now(UTC) - timedelta(days=1))
    result = await client.get(f"/api/v1/resources/{doc.id}")
    assert result.status_code == 200
    assert result.json()["data"]["name"] == "Document"
    assert len((await client.get(f"/api/v1/resources?parent_id={folder.id}")).json()["data"]) == 1
    assert (await client.get(f"/api/v1/resources/{space.id}")).status_code == 403


async def test_mutations_require_csrf_and_object_permissions(api, db, scene):
    client, state = api
    owner, actor, space, _, doc, dept, _ = scene
    payload = {
        "resource_type": "FOLDER",
        "name": "New",
        "department_id": str(dept.id),
        "parent_id": str(space.id),
    }
    assert (await client.post("/api/v1/resources", json=payload)).status_code == 403
    grant = {
        "principal_type": "USER",
        "principal_id": str(actor.id),
        "permission": "VIEW",
        "effect": "ALLOW",
        "reason": "review",
    }
    assert (await client.post(f"/api/v1/resources/{doc.id}/acl", json=grant)).status_code == 403
    assert (
        await client.post(
            f"/api/v1/resources/{doc.id}/break-glass",
            json={"permission": "VIEW", "reason": "incident", "minutes": 10},
        )
    ).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.post("/api/v1/resources", json=payload)).status_code == 403
    assert (await client.post(f"/api/v1/resources/{doc.id}/acl", json=grant)).status_code == 403
    state["actor"] = owner
    with (
        patch("app.resources.service.write_audit_event", new=AsyncMock()),
        patch("app.authorization.administration.write_audit_event", new=AsyncMock()),
    ):
        assert (await client.post("/api/v1/resources", json=payload)).status_code == 200
        response = await client.post(f"/api/v1/resources/{doc.id}/acl", json=grant)
        assert response.status_code == 200
        entry_id = response.json()["data"]["id"]
        assert (await client.get(f"/api/v1/resources/{doc.id}/acl")).status_code == 200
        assert (
            await client.delete(f"/api/v1/resources/{doc.id}/acl/{entry_id}")
        ).status_code == 200
        assert (await client.get(f"/api/v1/resources/{doc.id}/permissions/DOWNLOAD")).json()[
            "data"
        ]["decision"] == "ALLOW"


async def test_root_create_and_breakglass_only_system_admin(api, db, scene):
    client, state = api
    _, actor, _, _, doc, dept, _ = scene
    app.dependency_overrides[require_csrf] = lambda: None
    await binding(db, actor, "SYSTEM_ADMIN", valid_from=datetime.now(UTC) - timedelta(days=1))
    with (
        patch("app.authorization.administration.write_audit_event", new=AsyncMock()),
        patch("app.resources.service.write_audit_event", new=AsyncMock()),
    ):
        payload = {"resource_type": "SPACE", "name": "New space", "department_id": str(dept.id)}
        assert (await client.post("/api/v1/resources", json=payload)).status_code == 200
        assert (await client.get(f"/api/v1/resources/{doc.id}")).status_code == 403
        assert (
            await client.post(
                f"/api/v1/resources/{doc.id}/break-glass",
                json={"permission": "VIEW", "reason": "incident", "minutes": 10},
            )
        ).status_code == 200
        assert (await client.get(f"/api/v1/resources/{doc.id}")).status_code == 200
        assert (await client.get(f"/api/v1/resources/{doc.id}/permissions/DOWNLOAD")).json()[
            "data"
        ]["decision"] == "DENY"


async def test_validation_and_audit_outage_fail_closed(api, db, scene):
    client, state = api
    owner, actor, _, _, doc, dept, _ = scene
    state["actor"] = owner
    app.dependency_overrides[require_csrf] = lambda: None
    grant = {
        "principal_type": "USER",
        "principal_id": str(actor.id),
        "permission": "VIEW",
        "effect": "ALLOW",
        "reason": "review",
    }
    assert (
        await client.post(
            f"/api/v1/resources/{doc.id}/acl", json={**grant, "valid_until": "2030-01-01T00:00:00"}
        )
    ).status_code == 422
    with patch(
        "app.authorization.administration.write_audit_event",
        side_effect=OSError("sensitive filesystem path"),
    ):
        response = await client.post(f"/api/v1/resources/{doc.id}/acl", json=grant)
        assert response.status_code == 503
        assert "sensitive" not in response.text


async def test_role_binding_routes_require_acl_and_csrf(api, db, scene):
    client, state = api
    owner, actor, _, _, doc, _, _ = scene
    path = f"/api/v1/resources/{doc.id}/role-bindings"
    payload = {"user_id": str(actor.id), "role_name": "READER"}
    assert (await client.get(path)).status_code == 403
    assert (await client.post(path, json=payload)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.post(path, json=payload)).status_code == 403
    state["actor"] = owner
    with patch("app.authorization.administration.write_audit_event", new=AsyncMock()):
        result = await client.post(path, json=payload)
        assert result.status_code == 200
        binding_id = result.json()["data"]["id"]
        assert len((await client.get(path)).json()["data"]) == 1
        assert (await client.delete(path + "/" + binding_id)).status_code == 200


async def test_unauthenticated_resource_denied():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/resources")).status_code == 401
