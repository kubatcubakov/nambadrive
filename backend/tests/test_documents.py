import io
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from PIL import Image
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.documents.preview import render
from app.documents.service import DocumentService, read_verified
from app.documents.upload import UploadService
from app.main import app
from app.models.acl import HardPolicy
from app.models.resource import Resource
from app.storage.seaweed import Area, StorageError
from tests.test_authorization import acl
from tests.test_authorization import scene as authorization_scene
from tests.test_upload import MemoryStorage

scene = authorization_scene


@pytest.fixture
async def api(db, scene):
    from httpx import ASGITransport, AsyncClient

    from app.auth.dependencies import current_user
    from app.core.database import get_db

    state = {"actor": scene[1]}

    async def session():
        try:
            yield db
        except Exception:
            await db.rollback()
            for item in list(db.identity_map.values()):
                await db.refresh(item)
            raise

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[current_user] = lambda: state["actor"]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def clean(db, scene):
    storage = MemoryStorage()
    with patch("app.documents.upload.write_audit_event", new=AsyncMock()):
        service = UploadService(db, storage)
        version = await service.create(scene[0], scene[3].id, "hello.txt", io.BytesIO(b"hello"), {})
        scanner = Mock()
        scanner.scan.return_value = True
        await service.scan_one(scanner)
    return await db.get(Resource, version.document_id), version, storage


@pytest.fixture(autouse=True)
def audit():
    with patch("app.documents.service.write_audit_event", new=AsyncMock()) as event:
        yield event


async def test_every_document_route_denies_idor(api, clean):
    client, _ = api
    row, _, storage = clean
    app.dependency_overrides[require_csrf] = lambda: None
    with patch("app.api.v1.documents.create_storage", return_value=storage):
        for suffix in ["", "/download", "/preview"]:
            assert (await client.get(f"/api/v1/documents/{row.id}" + suffix)).status_code == 403
        for action, body in [
            ("rename", {"name": "new.txt"}),
            ("move", {"parent_id": str(row.parent_id)}),
            ("copy", {"parent_id": str(row.parent_id)}),
            ("restore", {}),
        ]:
            assert (
                await client.post(f"/api/v1/documents/{row.id}/{action}", json=body)
            ).status_code == 403
        assert (
            await client.put(f"/api/v1/documents/{row.id}/metadata", json={})
        ).status_code == 403
        assert (await client.delete(f"/api/v1/documents/{row.id}")).status_code == 403


async def test_reader_preview_allowed_download_separate(api, db, scene, clean):
    client, _ = api
    row, _, storage = clean
    for permission in ["VIEW", "PREVIEW"]:
        await acl(
            db,
            scene,
            resource=row,
            permission=permission,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
    with patch("app.api.v1.documents.create_storage", return_value=storage):
        assert (await client.get(f"/api/v1/documents/{row.id}")).status_code == 200
        preview = await client.get(f"/api/v1/documents/{row.id}/preview")
        assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
        assert preview.headers["Cache-Control"] == "no-store"
        assert (await client.get(f"/api/v1/documents/{row.id}/download")).status_code == 403
        await acl(
            db,
            scene,
            resource=row,
            permission="DOWNLOAD",
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
        download = await client.get(f"/api/v1/documents/{row.id}/download")
        assert download.status_code == 200 and download.content == b"hello"
        assert "attachment" in download.headers["Content-Disposition"]


async def test_document_mutations_csrf_and_trash_restore(api, scene, db, clean):
    client, state = api
    state["actor"] = scene[0]
    row, _, _ = clean
    path = f"/api/v1/documents/{row.id}"
    assert (await client.post(path + "/rename", json={"name": "new.txt"})).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.post(path + "/rename", json={"name": "new.exe"})).status_code == 422
    assert (await client.post(path + "/rename", json={"name": "new.txt"})).status_code == 200
    assert (
        await client.put(
            path + "/metadata",
            json={"description": "<script>inert text</script>", "tags": ["contract"]},
        )
    ).status_code == 200
    row.legal_hold = True
    await db.commit()
    assert (await client.delete(path)).status_code == 200
    assert (await client.get(path)).status_code == 403
    assert len((await client.get("/api/v1/documents/trash")).json()["data"]) == 1
    assert not (await AuthorizationService().authorize(db, scene[0], "PURGE", row.id)).allowed
    assert (await client.post(path + "/restore")).status_code == 200
    assert row.legal_hold


async def test_move_copy_preserve_policy_and_content(db, scene, clean):
    row, version, storage = clean
    owner, _, space, folder, *_ = scene
    folder.legal_hold = True
    folder.retention_until = datetime.now(UTC) + timedelta(days=365)
    folder.classification = "CONFIDENTIAL"
    db.add(HardPolicy(resource_id=folder.id, permission_id="DOWNLOAD", reason="restricted"))
    await db.commit()
    service = DocumentService(db, owner, {})
    copied = await service.copy(row.id, space.id, storage)
    assert copied.legal_hold and copied.classification == "CONFIDENTIAL"
    assert copied.retention_until is not None
    assert not (await AuthorizationService().authorize(db, owner, "DOWNLOAD", copied.id)).allowed
    cloned_version = await service.current(copied.id)
    assert cloned_version.id != version.id and cloned_version.sha256 == version.sha256
    await service.move(row.id, space.id)
    assert row.legal_hold and row.parent_id == space.id
    assert not (await AuthorizationService().authorize(db, owner, "DOWNLOAD", row.id)).allowed
    # Existing versions retain their original storage space/key after movement.
    target = io.BytesIO()
    read_verified(storage, version, target)
    assert target.read() == b"hello"


async def test_destination_create_is_required(db, scene, clean):
    row, _, storage = clean
    await acl(
        db, scene, resource=row, permission="COPY", valid_from=datetime.now(UTC) - timedelta(days=1)
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await DocumentService(db, scene[1], {}).copy(row.id, scene[2].id, storage)


async def test_copy_audit_failure_rolls_back(db, scene, clean, audit):
    row, _, storage = clean
    before = len((await db.scalars(select(Resource))).all())
    audit.side_effect = OSError("audit full")
    with pytest.raises(OSError):
        await DocumentService(db, scene[0], {}).copy(row.id, scene[2].id, storage)
    await db.rollback()
    assert len((await db.scalars(select(Resource))).all()) == before


async def test_corrupted_storage_never_served(api, scene, clean):
    client, state = api
    state["actor"] = scene[0]
    row, version, storage = clean
    for key in storage.objects:
        if key[0] == Area.DATA:
            storage.objects[key] = b"wrong"
    with pytest.raises(StorageError):
        read_verified(storage, version, io.BytesIO())
    with patch("app.api.v1.documents.create_storage", return_value=storage):
        assert (await client.get(f"/api/v1/documents/{row.id}/download")).status_code == 503


def test_raster_preview_strips_metadata_and_renders_pdf(tmp_path):
    image = Image.new("RGB", (20, 20), "blue")
    path = tmp_path / "test.png"
    image.save(path)
    result = render(str(path), "image/png", 0)
    assert Image.open(io.BytesIO(result)).size == (20, 20)
    path = tmp_path / "test.pdf"
    image.save(path, format="PDF")
    result = render(str(path), "application/pdf", 0)
    assert result.startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        render(str(path), "application/pdf", 2)
