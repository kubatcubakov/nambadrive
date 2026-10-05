"""Enumerate the current OpenAPI contract: future protected routes join this gate."""

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app

PUBLIC = {
    ("get", "/api/v1/auth/login"),
    ("get", "/api/v1/auth/callback"),
    ("get", "/api/v1/health/live"),
    ("get", "/api/v1/health/ready"),
    ("post", "/api/v1/shares/access"),
}
OPERATIONS = [
    (method, path)
    for path, methods in app.openapi()["paths"].items()
    for method in methods
    if (method, path) not in PUBLIC
]


def test_acceptance_inventory_covers_all_api_groups():
    assert len(OPERATIONS) >= 80
    assert {
        "/scim/v2/Users",
        "/api/v1/documents/{document_id}",
        "/api/v1/resources/{resource_id}/acl",
        "/api/v1/admin/dashboard",
    } <= {path for _, path in OPERATIONS}


@pytest.mark.parametrize("method,template", OPERATIONS)
async def test_every_protected_route_denies_anonymous_requests(db, method, template):
    identifier = str(uuid.uuid4())
    path = re.sub(r"\{[^}]+\}", identifier, template).replace(
        "/permissions/" + identifier, "/permissions/VIEW"
    )
    if template.endswith("/{action}"):
        path = path.rsplit("/", 1)[0] + "/approve"

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://drive.example.test"
        ) as client:
            response = await client.request(method.upper(), path, json={})
        assert response.status_code in {401, 403, 503}, (method, template, response.text)
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert identifier not in response.text
    finally:
        app.dependency_overrides.clear()


async def test_real_sessions_csrf_is_bound_and_disabled_identity_denies(db, tmp_path):
    from app.auth.sessions import create_session
    from app.core.config import get_settings
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User

    settings = get_settings()
    actor = User(authentik_sub="csrf-acceptance", username="actor", display_name="Actor")
    company = Company(name="CSRF acceptance")
    db.add_all([actor, company])
    await db.flush()
    department = Department(company_id=company.id, name="CSRF acceptance")
    db.add(department)
    await db.flush()
    resource = Resource(
        resource_type="SPACE",
        name="CSRF acceptance",
        owner_user_id=actor.id,
        department_id=department.id,
    )
    db.add(resource)
    await db.flush()
    first = await create_session(
        db, user=actor, settings=settings, ip=None, user_agent="acceptance"
    )
    second = await create_session(
        db, user=actor, settings=settings, ip=None, user_agent="acceptance"
    )
    await db.commit()

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://drive.example.test",
            cookies={settings.session_cookie_name: first},
        ) as client:
            csrf = (await client.get("/api/v1/auth/csrf")).json()["data"]["csrf_token"]
            path = f"/api/v1/resources/{resource.id}/security"
            payload = {
                "classification": "PUBLIC",
                "inherit_acl": True,
                "reason": "Acceptance CSRF verification",
            }
            assert (await client.put(path, json=payload)).status_code == 403
            client.cookies.set(settings.session_cookie_name, second)
            assert (
                await client.put(path, json=payload, headers={"X-CSRF-Token": csrf})
            ).status_code == 403
            fresh = (await client.get("/api/v1/auth/csrf")).json()["data"]["csrf_token"]
            assert fresh != csrf
            response = await client.put(path, json=payload, headers={"X-CSRF-Token": fresh})
            assert response.status_code == 200
            await db.refresh(resource)
            assert resource.classification == "PUBLIC"
            actor.enabled = False
            await db.commit()
            assert (await client.get(f"/api/v1/resources/{resource.id}")).status_code == 401
            assert (await client.get("/api/v1/auth/csrf")).status_code == 401
        audit = (tmp_path / "audit.jsonl").read_text()
        assert all(token not in audit for token in (first, second, csrf, fresh))
    finally:
        app.dependency_overrides.clear()
