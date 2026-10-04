import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access_requests.service import AccessRequestService
from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.main import app
from app.models.access_request import AccessRequest
from app.models.acl import ACLEntry, HardPolicy
from app.models.organization import DepartmentManager
from tests.test_authorization import acl
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_organization import user

api, clean, scene = api_fixture, clean_fixture, scene_fixture


@pytest.fixture(autouse=True)
def audits():
    with (
        patch("app.access_requests.service.write_audit_event", new=AsyncMock()) as event,
        patch("app.authorization.administration.write_audit_event", new=AsyncMock()) as acl_event,
    ):
        yield event, acl_event


@pytest.fixture
async def discoverable(db, scene, clean):
    row, _, _ = clean
    await acl(
        db,
        scene,
        resource=row,
        permission="REQUEST_ACCESS_DISCOVERY",
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    return row


async def test_discovery_default_deny_minimal_metadata_strict_hidden(api, db, scene, clean):
    client, _ = api
    row, _, _ = clean
    assert (await client.get("/api/v1/access-requests/discovery?q=hello")).json() == {"data": []}
    await acl(
        db,
        scene,
        resource=row,
        permission="REQUEST_ACCESS_DISCOVERY",
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    response = await client.get("/api/v1/access-requests/discovery?q=hello")
    assert response.headers["Cache-Control"] == "no-store"
    result = response.json()["data"][0]
    assert set(result) == {"id", "name", "type", "owner_id", "department_id"}
    assert (await client.get(f"/api/v1/documents/{row.id}")).status_code == 403
    scene[3].classification = "STRICTLY_CONFIDENTIAL"
    await db.commit()
    assert (await client.get("/api/v1/access-requests/discovery?q=hello")).json() == {"data": []}
    app.dependency_overrides[require_csrf] = lambda: None
    assert (
        await client.post(
            "/api/v1/access-requests",
            json={"resource_id": str(row.id), "permission": "VIEW", "reason": "needed"},
        )
    ).status_code == 403


async def test_request_csrf_idor_and_single_decision(api, db, scene, discoverable):
    client, state = api
    row = discoverable
    payload = {"resource_id": str(row.id), "permission": "DOWNLOAD", "reason": "contract work"}
    assert (await client.post("/api/v1/access-requests", json=payload)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (
        await client.post(
            "/api/v1/access-requests", json={**payload, "resource_id": str(uuid.uuid4())}
        )
    ).status_code == 403
    response = await client.post("/api/v1/access-requests", json=payload)
    assert response.status_code == 201
    request_id = response.json()["data"]["id"]
    assert len((await client.get("/api/v1/access-requests/mine")).json()["data"]) == 1
    assert (await client.get("/api/v1/access-requests/inbox")).json()["data"] == []
    assert (
        await client.post(
            f"/api/v1/access-requests/{request_id}/approve", json={"reason": "self approval"}
        )
    ).status_code == 403
    state["actor"] = scene[0]
    assert len((await client.get("/api/v1/access-requests/inbox")).json()["data"]) == 1
    result = await client.post(
        f"/api/v1/access-requests/{request_id}/approve", json={"reason": "approved"}
    )
    assert result.status_code == 200 and result.json()["data"]["status"] == "APPROVED"
    assert (await AuthorizationService().authorize(db, scene[1], "DOWNLOAD", row.id)).allowed
    assert (
        await client.post(f"/api/v1/access-requests/{request_id}/deny", json={"reason": "again"})
    ).status_code == 409


async def test_temporary_grant_exact_permission_and_deny_wins(db, scene, discoverable):
    row = discoverable
    now = datetime.now(UTC)
    request = await AccessRequestService(db, scene[1], {}).create(
        row.id, "DOWNLOAD", "work", now + timedelta(hours=1)
    )
    await AccessRequestService(db, scene[0], {}).decide(
        request.id, True, "one hour", now + timedelta(days=1)
    )
    entry = await db.get(ACLEntry, request.acl_entry_id)
    assert entry.permission_id == "DOWNLOAD" and not entry.propagate_to_children
    from app.authorization.service import utc

    assert utc(entry.valid_until) == utc(request.requested_until)
    assert (await AuthorizationService().authorize(db, scene[1], "DOWNLOAD", row.id)).allowed
    assert not (await AuthorizationService().authorize(db, scene[1], "VIEW", row.id)).allowed
    assert not (
        await AuthorizationService().authorize(
            db, scene[1], "DOWNLOAD", row.id, now=now + timedelta(hours=2)
        )
    ).allowed
    await acl(
        db,
        scene,
        resource=row,
        permission="DOWNLOAD",
        effect="DENY",
        valid_from=now - timedelta(days=1),
    )
    assert not (await AuthorizationService().authorize(db, scene[1], "DOWNLOAD", row.id)).allowed


async def test_one_department_manager_is_enough(db, scene, discoverable):
    requester = AccessRequestService(db, scene[1], {})
    request = await requester.create(discoverable.id, "EDIT", "work", None)
    manager = await user(db)
    db.add(
        DepartmentManager(
            department_id=scene[5].id,
            user_id=manager.id,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db.commit()
    await AccessRequestService(db, manager, {}).decide(request.id, True, "team work", None)
    assert request.status == "APPROVED"
    assert (await AuthorizationService().authorize(db, scene[1], "EDIT", discoverable.id)).allowed


async def test_explicit_acl_admin_not_owner_cannot_approve(db, scene, discoverable):
    request = await AccessRequestService(db, scene[1], {}).create(
        discoverable.id, "VIEW", "work", None
    )
    await acl(
        db,
        scene,
        resource=discoverable,
        permission="CHANGE_ACL",
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    with pytest.raises(HTTPException):
        await AccessRequestService(db, scene[1], {}).decide(request.id, True, "self", None)
    assert request.status == "PENDING"


async def test_approval_audit_failure_rolls_back_grant_and_request(db, scene, discoverable, audits):
    request = await AccessRequestService(db, scene[1], {}).create(
        discoverable.id, "EDIT", "work", None
    )
    audits[0].side_effect = OSError("full audit disk")
    with pytest.raises(OSError):
        await AccessRequestService(db, scene[0], {}).decide(request.id, True, "approved", None)
    await db.rollback()
    await db.refresh(request)
    assert request.status == "PENDING" and request.acl_entry_id is None
    assert not (await db.scalars(select(ACLEntry).where(ACLEntry.permission_id == "EDIT"))).all()


async def test_deny_creates_no_acl(db, scene, discoverable):
    request = await AccessRequestService(db, scene[1], {}).create(
        discoverable.id, "EDIT", "work", None
    )
    await AccessRequestService(db, scene[0], {}).decide(request.id, False, "not needed", None)
    assert request.status == "DENIED" and request.acl_entry_id is None
    assert not (
        await AuthorizationService().authorize(db, scene[1], "EDIT", discoverable.id)
    ).allowed


@pytest.mark.parametrize(
    "blocked", ["disabled_requester", "hard_policy", "expired_request", "expired_approval"]
)
async def test_invalid_approval_closed(db, scene, discoverable, blocked):
    request = await AccessRequestService(db, scene[1], {}).create(
        discoverable.id, "EDIT", "work", None
    )
    until = None
    if blocked == "disabled_requester":
        scene[1].enabled = False
    elif blocked == "hard_policy":
        db.add(
            HardPolicy(resource_id=discoverable.id, permission_id="CHANGE_ACL", reason="blocked")
        )
    elif blocked == "expired_request":
        request.requested_until = datetime.now(UTC) - timedelta(seconds=1)
    else:
        until = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    with pytest.raises((ValueError, HTTPException)):
        await AccessRequestService(db, scene[0], {}).decide(request.id, True, "approved", until)
    assert request.status == "PENDING"


async def test_duplicate_pending_and_invalid_requests(db, scene, discoverable):
    service = AccessRequestService(db, scene[1], {})
    for permission, reason, until in [
        ("CHANGE_ACL", "work", None),
        ("VIEW", " ", None),
        ("VIEW", "work", datetime.now(UTC) - timedelta(seconds=1)),
    ]:
        with pytest.raises(ValueError):
            await service.create(discoverable.id, permission, reason, until)
    await service.create(discoverable.id, "VIEW", "work", None)
    with pytest.raises(IntegrityError):
        await service.create(discoverable.id, "VIEW", "duplicate", None)
    await db.rollback()


async def test_postgres_concurrent_approval_creates_one_grant():
    import asyncio
    import os

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("Requires PostgreSQL row locks")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, requester_id, cid, did, sid, rid, request_id = [uuid.uuid4() for _ in range(7)]
    try:
        async with factory() as db:
            db.add_all(
                [
                    User(
                        id=value,
                        authentik_sub=str(value),
                        username="request-test",
                        display_name="test",
                    )
                    for value in [uid, requester_id]
                ]
            )
            db.add(Company(id=cid, name=str(cid)))
            await db.flush()
            db.add(Department(id=did, company_id=cid, name="test"))
            await db.flush()
            db.add(
                Resource(
                    id=sid, resource_type="SPACE", name="test", owner_user_id=uid, department_id=did
                )
            )
            await db.flush()
            db.add(
                Resource(
                    id=rid,
                    resource_type="DOCUMENT",
                    parent_id=sid,
                    name="test.txt",
                    owner_user_id=uid,
                    department_id=did,
                )
            )
            await db.flush()
            db.add(
                AccessRequest(
                    id=request_id,
                    resource_id=rid,
                    requested_by=requester_id,
                    permission_id="VIEW",
                    reason="work",
                )
            )
            await db.commit()

        async def approve():
            async with factory() as db:
                actor = await db.get(User, uid)
                try:
                    await AccessRequestService(db, actor, {}).decide(
                        request_id, True, "approved", None
                    )
                    return True
                except HTTPException as error:
                    assert error.status_code == 409
                    await db.rollback()
                    return False

        assert sum(await asyncio.gather(*(approve() for _ in range(5)))) == 1
        async with factory() as db:
            grants = (await db.scalars(select(ACLEntry).where(ACLEntry.resource_id == rid))).all()
            assert len(grants) == 1 and grants[0].principal_id == requester_id
    finally:
        async with factory() as db:
            for model, condition in [
                (AccessRequest, AccessRequest.resource_id == rid),
                (ACLEntry, ACLEntry.resource_id == rid),
                (Resource, Resource.id == rid),
                (Resource, Resource.id == sid),
                (Department, Department.id == did),
                (Company, Company.id == cid),
                (User, User.id.in_([uid, requester_id])),
            ]:
                await db.execute(delete(model).where(condition))
            await db.commit()
        await engine.dispose()
