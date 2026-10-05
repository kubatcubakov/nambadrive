import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings
from app.documents.upload import UploadService
from app.models.acl import HardPolicy
from app.models.document import DocumentVersion
from app.models.office import OfficeRoom, OfficeSession
from app.models.resource import Resource
from app.models.session import ApplicationSession
from app.office.security import callback_download_url, verify_outbox
from app.office.service import OfficeService
from app.office.templates import blank
from tests.test_authorization import scene as authorization_scene
from tests.test_documents import api as documents_api
from tests.test_upload import MemoryStorage

scene = authorization_scene
api = documents_api


@pytest.fixture
def settings():
    return Settings(
        office_public_url="https://office.test",
        office_internal_url="http://onlyoffice",
        office_backend_url="http://backend:8000",
        office_browser_secret=SecretStr("b" * 32),
        office_outbox_secret=SecretStr("o" * 32),
    )


@pytest.fixture(autouse=True)
def audit():
    with (
        patch("app.documents.upload.write_audit_event", new=AsyncMock()),
        patch("app.documents.service.write_audit_event", new=AsyncMock()),
    ):
        yield


@pytest.fixture
async def office(db, scene, settings):
    actor = scene[0]
    storage = MemoryStorage()
    storage.max_bytes = 500 * 1024 * 1024
    version = await UploadService(db, storage).create(
        actor, scene[3].id, "test.docx", blank("docx"), {}
    )
    scanner = Mock()
    scanner.scan.return_value = True
    await UploadService(db, storage).scan_one(scanner)
    application = ApplicationSession(
        user_id=actor.id,
        session_hash=uuid.uuid4().hex * 2,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(application)
    await db.commit()
    service = OfficeService(db, settings, {})
    config = await service.open(actor, version.document_id, application)
    session_id = uuid.UUID(config["config"]["editorConfig"]["callbackUrl"].rsplit("/", 1)[1])
    return service, version, application, storage, config, session_id


def signed(payload, settings):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "payload": payload,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.office_outbox_secret.get_secret_value(),
        algorithm="HS256",
    )


@pytest.mark.parametrize("extension", ["docx", "xlsx", "pptx"])
def test_valid_blank_office_templates(extension):
    from app.documents.validation import validate

    assert "officedocument" in validate(blank(extension), "test." + extension, 500 * 1024 * 1024)


def test_separate_signing_keys_and_callback_ssrf(settings):
    payload = {"key": "test", "status": 4}
    assert verify_outbox(signed(payload, settings), settings) == payload
    with pytest.raises(HTTPException):
        verify_outbox(
            jwt.encode(
                {"payload": payload},
                settings.office_browser_secret.get_secret_value(),
                algorithm="HS256",
            ),
            settings,
        )
    for url in [
        "http://169.254.169.254/latest",
        "http://onlyoffice@evil/cache/files/x",
        "http://onlyoffice/command",
        "http://onlyoffice/cache/files/../command",
        "https://office.test.evil/cache/files/x",
        "http://onlyoffice/cache/files/x#fragment",
    ]:
        with pytest.raises(HTTPException):
            callback_download_url(url, settings)
    assert (
        callback_download_url(
            "https://office.test/cache/files/key/output.docx?expires=123", settings
        )
        == "http://onlyoffice/cache/files/key/output.docx?expires=123"
    )


async def test_coediting_uses_shared_key_and_config_never_leaks_secret(db, scene, office, settings):
    service, version, application, _, first, _ = office
    second = await service.open(scene[0], version.document_id, application)
    assert first["config"]["document"]["key"] == second["config"]["document"]["key"]
    assert "b" * 32 not in str(first) and "o" * 32 not in str(first)
    with pytest.raises(HTTPException):
        verify_outbox(first["config"]["token"], settings)


async def test_signed_content_route_rejects_browser_token_and_requires_live_session(
    api, office, settings
):
    client, _ = api
    _, version, application, storage, config, session_id = office
    path = f"/api/v1/office/internal/content/{session_id}"
    with (
        patch("app.api.v1.office.get_settings", return_value=settings),
        patch("app.api.v1.office.create_storage", return_value=storage),
    ):
        assert (await client.get(path)).status_code == 403
        assert (
            await client.get(path, headers={"Authorization": "Bearer " + config["config"]["token"]})
        ).status_code == 403
        token = signed({"url": settings.office_backend_url + path}, settings)
        response = await client.get(path, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200 and response.content.startswith(b"PK")
        assert len(response.content) == version.size
        application.revoked_at = datetime.now(UTC)
        assert (
            await client.get(path, headers={"Authorization": "Bearer " + token})
        ).status_code == 403


async def test_save_is_quarantined_and_idempotent(db, office):
    service, version, _, storage, config, session_id = office
    payload = {
        "key": config["config"]["document"]["key"],
        "status": 6,
        "filetype": "docx",
        "users": [str((await db.get(OfficeSession, session_id)).user_id)],
        "url": "http://onlyoffice/cache/files/key/output.docx",
    }

    async def download(url, source):
        source.write(blank("docx").getvalue())
        source.seek(0)

    with patch.object(service, "download", new=download):
        assert await service.callback(session_id, payload, storage) == {"error": 0}
        assert await service.callback(session_id, payload, storage) == {"error": 0}
    versions = list(
        (
            await db.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == version.document_id)
            )
        ).all()
    )
    assert len(versions) == 2
    pending = next(v for v in versions if v.status == "PENDING")
    assert pending.ingest_permission == "EDIT" and version.is_current
    scanner = Mock()
    scanner.scan.return_value = True
    await UploadService(db, storage).scan_one(scanner)
    assert pending.is_current
    assert (await service.session(session_id))[1].id.hex == payload["key"]


@pytest.mark.parametrize(
    "failure", ["wrong-key", "disabled", "expired", "revoked", "hard-policy", "stale"]
)
async def test_callback_rejects_stale_or_revoked_editor(db, scene, office, failure):
    service, version, application, storage, config, session_id = office
    payload = {"key": config["config"]["document"]["key"], "status": 4}
    if failure == "wrong-key":
        payload["key"] = "wrong"
    elif failure == "disabled":
        scene[0].enabled = False
    elif failure == "expired":
        session = await db.get(OfficeSession, session_id)
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif failure == "revoked":
        application.revoked_at = datetime.now(UTC)
    elif failure == "hard-policy":
        db.add(HardPolicy(resource_id=version.document_id, permission_id="EDIT", reason="frozen"))
    elif failure == "stale":
        await UploadService(db, storage).new_version(
            scene[0], version.document_id, "test.docx", blank("docx"), {}
        )
        scanner = Mock()
        scanner.scan.return_value = True
        await UploadService(db, storage).scan_one(scanner)
    await db.commit()
    with pytest.raises(HTTPException):
        await service.callback(session_id, payload, storage)


async def test_callback_body_must_match_signed_parameters(api, office, settings):
    client, _ = api
    _, _, _, storage, config, session_id = office
    payload = {"key": config["config"]["document"]["key"], "status": 4}
    with (
        patch("app.api.v1.office.get_settings", return_value=settings),
        patch("app.api.v1.office.create_storage", return_value=storage),
    ):
        response = await client.post(
            f"/api/v1/office/internal/callback/{session_id}",
            json={**payload, "status": 2},
            headers={"Authorization": "Bearer " + signed(payload, settings)},
        )
        assert response.status_code == 403


async def test_closed_room_replay_and_pending_save_blocks_reopen(db, scene, office):
    service, version, application, storage, config, session_id = office
    payload = {
        "key": config["config"]["document"]["key"],
        "status": 2,
        "filetype": "docx",
        "users": [str(scene[0].id)],
        "url": "http://onlyoffice/cache/files/key/output.docx",
    }

    async def download(url, source):
        source.write(blank("docx").getvalue())
        source.seek(0)

    with patch.object(service, "download", new=download):
        await service.callback(session_id, payload, storage)
        assert await service.callback(session_id, payload, storage) == {"error": 0}
    with pytest.raises(HTTPException):
        await service.open(scene[0], version.document_id, application)
    assert await db.scalar(select(func.count()).select_from(OfficeRoom)) == 1
    assert (await db.get(Resource, version.document_id)).state == "ACTIVE"


async def test_public_office_routes_require_acl_and_csrf(api, office, scene, settings):
    from app.auth.dependencies import require_csrf
    from app.main import app

    client, state = api
    _, version, application, storage, _, _ = office
    with (
        patch("app.api.v1.office.get_settings", return_value=settings),
        patch("app.api.v1.office.create_storage", return_value=storage),
        patch(
            "app.api.v1.office.get_session_user",
            new=AsyncMock(return_value=(application, scene[0])),
        ),
    ):
        path = f"/api/v1/office/{version.document_id}/session"
        assert (await client.post(path)).status_code == 403
        app.dependency_overrides[require_csrf] = lambda: None
        assert (await client.post(path)).status_code == 403
        payload = {"parent_id": str(scene[3].id), "name": "New", "format": "docx"}
        assert (await client.post("/api/v1/office/create", json=payload)).status_code == 403
        state["actor"] = scene[0]
        assert (await client.post(path)).status_code == 200
        response = await client.post("/api/v1/office/create", json=payload)
        assert response.status_code == 202 and response.json()["data"]["status"] == "PENDING"


async def test_office_save_audit_failure_is_atomic(db, office):
    from app.models.office import OfficeSave

    service, version, _, storage, config, session_id = office
    actor = (await db.get(OfficeSession, session_id)).user_id
    docid = version.document_id
    payload = {
        "key": config["config"]["document"]["key"],
        "status": 6,
        "filetype": "docx",
        "users": [str(actor)],
        "url": "http://onlyoffice/cache/files/key/output.docx",
    }

    async def download(url, source):
        source.write(blank("docx").getvalue())
        source.seek(0)

    with (
        patch.object(service, "download", new=download),
        patch(
            "app.documents.service.write_audit_event",
            new=AsyncMock(side_effect=OSError("audit unavailable")),
        ),
    ):
        with pytest.raises(OSError):
            await service.callback(session_id, payload, storage)
    await db.rollback()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == docid)
        )
        == 1
    )
    assert await db.scalar(select(func.count()).select_from(OfficeSave)) == 0


async def test_editor_session_recheck_refreshes_cached_revocation(db, office):
    from sqlalchemy import update

    service, _, _, _, _, session_id = office
    session = await db.get(OfficeSession, session_id)
    assert (await service.valid_actor(session)).enabled
    await db.execute(
        update(OfficeSession)
        .where(OfficeSession.id == session_id)
        .values(revoked_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    with pytest.raises(HTTPException) as failure:
        await service.valid_actor(session)
    assert failure.value.status_code == 403
