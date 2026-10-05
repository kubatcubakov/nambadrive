from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.drive.service import DriveService
from app.main import app
from app.models.acl import HardPolicy
from app.models.drive import Favorite, RecentDocument
from app.models.organization import DepartmentMembership
from app.models.share import ExternalShare
from app.shares.service import ShareService
from tests.test_authorization import acl
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture

api, clean, scene, admin = api_fixture, clean_fixture, scene_fixture, admin_fixture


async def test_every_drive_view_is_acl_filtered_and_admin_has_no_content(
    api, db, scene, clean, admin
):
    client, state = api
    for actor in [scene[1], admin]:
        state["actor"] = actor
        for view in ["mine", "shared", "spaces", "departments", "recent", "favorites", "trash"]:
            result = await client.get("/api/v1/drive", params={"view": view})
            assert result.status_code == 200 and result.json()["data"] == []
            assert result.headers["Cache-Control"] == "no-store"
    state["actor"] = scene[0]
    assert [r["id"] for r in (await client.get("/api/v1/drive")).json()["data"]] == [
        str(clean[0].id)
    ]
    assert (await client.get("/api/v1/admin/dashboard")).status_code == 403
    state["actor"] = admin
    result = await client.get("/api/v1/admin/dashboard")
    assert result.status_code == 200 and result.json()["data"]["logical_bytes"] == clean[1].size
    assert "name" not in str(result.json()) and str(clean[0].id) not in str(result.json())
    assert (await client.get("/api/v1/documents/" + str(clean[0].id))).status_code == 403


async def test_favorites_are_private_idempotent_csrf_and_fresh_acl(api, db, scene, clean):
    client, state = api
    path = "/api/v1/favorites/" + str(clean[0].id)
    state["actor"] = scene[0]
    assert (await client.put(path)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    state["actor"] = scene[1]
    assert (await client.put(path)).status_code == 403
    grant = await acl(
        db, scene, resource=clean[0], valid_from=datetime.now(UTC) - timedelta(days=1)
    )
    await db.commit()
    assert (await client.put(path)).status_code == 200
    assert (await client.put(path)).status_code == 200
    rows = (await client.get("/api/v1/drive?view=favorites")).json()["data"]
    assert len(rows) == 1 and rows[0]["favorite"]
    state["actor"] = scene[0]
    assert (await client.get("/api/v1/drive?view=favorites")).json()["data"] == []
    state["actor"] = scene[1]
    grant.revoked_at = datetime.now(UTC)
    await db.commit()
    assert (await client.get("/api/v1/drive?view=favorites")).json()["data"] == []
    # Own removal remains possible without disclosing revoked document metadata.
    assert (await client.delete(path)).status_code == 200
    assert not (await db.scalars(select(Favorite))).all()


async def test_recent_tracks_only_successful_audited_views_and_rechecks_permissions(
    api, db, scene, clean
):
    client, state = api
    document = clean[0]
    path = "/api/v1/documents/" + str(document.id)
    assert (await client.get(path)).status_code == 403
    assert not (await db.scalars(select(RecentDocument))).all()
    state["actor"] = scene[0]
    assert (await client.get(path)).status_code == 200
    rows = (await client.get("/api/v1/drive?view=recent")).json()["data"]
    assert len(rows) == 1 and rows[0]["owner_name"] == scene[0].display_name
    assert (await client.get("/api/v1/drive?view=recent")).json()["data"] == rows
    document.classification = "STRICTLY_CONFIDENTIAL"
    db.add(HardPolicy(resource_id=document.id, permission_id="VIEW", reason="suspended"))
    await db.commit()
    assert (await client.get("/api/v1/drive?view=recent")).json()["data"] == []


async def test_department_view_requires_view_not_membership_alone(api, db, scene, clean):
    client, state = api
    outsider, department = scene[1], scene[6]
    db.add(DepartmentMembership(user_id=outsider.id, department_id=department.id, kind="PRIMARY"))
    await db.commit()
    assert (await client.get("/api/v1/drive?view=departments")).json()["data"] == []
    await acl(db, scene, resource=clean[0], valid_from=datetime.now(UTC) - timedelta(days=1))
    await db.commit()
    rows = (await client.get("/api/v1/drive?view=departments")).json()["data"]
    assert len(rows) == 1 and rows[0]["department_id"] == str(department.id)
    assert len((await client.get("/api/v1/drive?view=shared")).json()["data"]) == 1
    assert (await client.get("/api/v1/drive?view=mine")).json()["data"] == []


async def test_security_policy_change_requires_acl_csrf_audit_and_revokes_old_shares(
    api, db, scene, clean, admin
):
    client, state = api
    document = clean[0]
    for resource in [scene[2], scene[3], document]:
        resource.classification = "PUBLIC"
    await db.commit()
    share, _ = await ShareService(db, {}).create(scene[0], document.id)
    path = "/api/v1/resources/" + str(document.id) + "/security"
    body = {"classification": "CONFIDENTIAL", "inherit_acl": False, "reason": "contract policy"}
    app.dependency_overrides[require_csrf] = lambda: None
    for actor in [scene[1], admin]:
        state["actor"] = actor
        assert (await client.put(path, json=body)).status_code == 403
    state["actor"] = scene[0]
    app.dependency_overrides.pop(require_csrf)
    assert (await client.put(path, json=body)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put(path, json=body)).status_code == 200
    assert document.classification == "CONFIDENTIAL" and not document.inherit_acl
    assert (await db.get(ExternalShare, share.id)).revoked_at
    assert not (
        await AuthorizationService().authorize(db, scene[0], "EXTERNAL_SHARE", document.id)
    ).allowed
    assert (await client.put(path, json={**body, "classification": "PUBLIC"})).status_code == 200
    assert (await db.get(ExternalShare, share.id)).revoked_at


async def test_security_policy_audit_failure_rolls_back(api, db, scene, clean):
    client, state = api
    state["actor"] = scene[0]
    app.dependency_overrides[require_csrf] = lambda: None
    await db.commit()
    path = "/api/v1/resources/" + str(clean[0].id) + "/security"
    with patch("app.audit.writer.write_audit_event", new=AsyncMock(side_effect=OSError("full"))):
        result = await client.put(
            path,
            json={
                "classification": "STRICTLY_CONFIDENTIAL",
                "inherit_acl": False,
                "reason": "test",
            },
        )
    assert result.status_code == 503
    assert clean[0].classification == "INTERNAL" and clean[0].inherit_acl


async def test_resource_capabilities_no_idor_and_reader_no_download(api, db, scene, clean):
    client, _ = api
    path = "/api/v1/resources/" + str(clean[0].id) + "/capabilities"
    assert (await client.get(path)).status_code == 403
    for permission in ["VIEW", "PREVIEW"]:
        await acl(
            db,
            scene,
            resource=clean[0],
            permission=permission,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
    await db.commit()
    data = (await client.get(path)).json()["data"]
    assert (
        "VIEW" in data and "PREVIEW" in data and "DOWNLOAD" not in data and "CHANGE_ACL" not in data
    )


async def test_pagination_counts_visible_rows_only(db, scene):
    import uuid

    from app.models.resource import Resource

    # Hidden rows sort before visible rows; they must not consume page positions.
    for index in range(103):
        db.add(
            Resource(
                id=uuid.uuid4(),
                resource_type="SPACE",
                name=f"{index:03}",
                owner_user_id=scene[1].id if index < 2 else scene[0].id,
                department_id=scene[5].id,
                classification="STRICTLY_CONFIDENTIAL",
            )
        )
    await db.commit()
    service = DriveService(db, scene[0], {})
    first = await service.listing("spaces", page=1)
    second = await service.listing("spaces", page=2)
    assert len(first) == 100 and len(second) == 2  # Includes scene's original owned space.
    assert not any(row["name"] in {"000", "001"} for row in first + second)
    assert len({row["id"] for row in first + second}) == 102
