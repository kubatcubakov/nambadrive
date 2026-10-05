import io
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.documents.service import DocumentService
from app.documents.upload import UploadService
from app.governance.cleanup import CleanupWorker
from app.main import app
from app.models.metadata import DocumentMetadata
from app.models.quota import QuotaIncident, QuotaLimit, StorageReservation
from app.quotas.service import QuotaService
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture
from tests.test_governance import disposable as disposable_fixture
from tests.test_office import office as office_fixture
from tests.test_office import settings as settings_fixture

office, settings = office_fixture, settings_fixture

api, clean, scene, admin, disposable = (
    api_fixture,
    clean_fixture,
    scene_fixture,
    admin_fixture,
    disposable_fixture,
)


@pytest.fixture(autouse=True)
def audits():
    with (
        patch("app.quotas.service.write_audit_event", new=AsyncMock()) as quota,
        patch("app.documents.upload.write_audit_event", new=AsyncMock()),
        patch("app.documents.service.write_audit_event", new=AsyncMock()),
        patch("app.governance.cleanup.write_audit_event", new=AsyncMock()),
    ):
        yield quota


async def test_admin_configuration_csrf_and_no_content_access(api, db, scene, clean, admin):
    client, state = api
    row, _, _ = clean
    payload = {
        "subject_type": "USER",
        "subject_id": str(scene[0].id),
        "limit_bytes": 0,
        "reason": "quota",
    }
    state["actor"] = scene[0]
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put("/api/v1/quotas", json=payload)).status_code == 403
    assert (await client.get("/api/v1/quotas/reservations")).status_code == 403
    state["actor"] = admin
    app.dependency_overrides.pop(require_csrf)
    assert (await client.put("/api/v1/quotas", json=payload)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put("/api/v1/quotas", json=payload)).status_code == 200
    assert (await client.get(f"/api/v1/documents/{row.id}")).status_code == 403
    state["actor"] = scene[0]
    response = await client.get("/api/v1/quotas/me")
    assert response.json()["data"] == {"used_bytes": 5, "limit_bytes": 0}
    assert response.headers["Cache-Control"] == "no-store"


async def test_versions_are_charged_and_over_quota_writes_never_start(
    db, scene, clean, admin, audits
):
    row, version, storage = clean
    quota = QuotaService(db, admin, {})
    await quota.configure("USER", scene[0].id, 10, "limit")
    before = dict(storage.objects)
    with pytest.raises(HTTPException) as error:
        await UploadService(db, storage).new_version(
            scene[0], row.id, "hello.txt", io.BytesIO(b"123456"), {}
        )
    assert error.value.status_code == 413 and storage.objects == before
    assert (await db.scalars(select(QuotaIncident))).all()
    assert audits.call_args.args[0] == "quota_exceeded"
    pending = await UploadService(db, storage).new_version(
        scene[0], row.id, "hello.txt", io.BytesIO(b"12345"), {}
    )
    assert pending.status == "PENDING" and await quota.usage("USER", scene[0].id) == 10
    assert not (await db.scalars(select(StorageReservation))).all()


async def test_parent_department_quota_counts_sections(db, scene, clean, admin):
    row, _, storage = clean
    quota = QuotaService(db, admin, {})
    await quota.configure("DEPARTMENT", scene[5].id, 5, "department cap")
    assert await quota.usage("DEPARTMENT", scene[5].id) == 5
    with pytest.raises(HTTPException):
        await UploadService(db, storage).new_version(
            scene[0], row.id, "hello.txt", io.BytesIO(b"1"), {}
        )


async def test_project_assignment_checks_company_and_existing_usage(api, db, scene, clean, admin):
    from app.models.organization import Company

    client, state = api
    state["actor"] = scene[0]
    row, _, storage = clean
    service = QuotaService(db, admin, {})
    project = await service.create_project(scene[5].company_id, "Project")
    await service.configure("PROJECT", project.id, 4, "cap")
    app.dependency_overrides[require_csrf] = lambda: None
    response = await client.put(
        f"/api/v1/documents/{row.id}/metadata", json={"project_id": str(project.id)}
    )
    assert response.status_code == 413
    assert await db.get(DocumentMetadata, row.id) is None
    await service.configure("PROJECT", project.id, 5, "cap")
    assert (
        await client.put(
            f"/api/v1/documents/{row.id}/metadata", json={"project_id": str(project.id)}
        )
    ).status_code == 200
    assert await service.usage("PROJECT", project.id) == 5
    with pytest.raises(HTTPException):
        await UploadService(db, storage).new_version(
            scene[0], row.id, "hello.txt", io.BytesIO(b"1"), {}
        )
    company = Company(name="Other company")
    db.add(company)
    await db.commit()
    other = await service.create_project(company.id, "Other")
    assert (
        await client.put(f"/api/v1/documents/{row.id}/metadata", json={"project_id": str(other.id)})
    ).status_code == 422
    choices = (await client.get(f"/api/v1/quotas/projects-for/{row.id}")).json()["data"]
    assert [choice["id"] for choice in choices] == [str(project.id)]


async def test_copy_restore_enforce_quota(api, db, scene, clean, admin):
    client, state = api
    state["actor"] = scene[0]
    row, version, storage = clean
    await QuotaService(db, admin, {}).configure("USER", scene[0].id, 9, "cap")
    app.dependency_overrides[require_csrf] = lambda: None
    before = dict(storage.objects)
    with patch("app.api.v1.documents.create_storage", return_value=storage):
        assert (
            await client.post(
                f"/api/v1/documents/{row.id}/copy", json={"parent_id": str(scene[2].id)}
            )
        ).status_code == 413
        assert (
            await client.post(f"/api/v1/documents/{row.id}/versions/{version.id}/restore")
        ).status_code == 413
    assert storage.objects == before


async def test_trash_counts_until_physical_purge(db, scene, disposable):
    row, version, storage = disposable
    quota = QuotaService(db, scene[0], {})
    await DocumentService(db, scene[0], {}).trash(row.id)
    assert await quota.usage("USER", scene[0].id) == 5
    row.deleted_at = datetime.now(UTC) - timedelta(days=31)
    await db.commit()
    await CleanupWorker(db, storage).process_one()
    assert version.purged_at and await quota.usage("USER", scene[0].id) == 0


async def test_quota_configuration_audit_failure_rolls_back(db, scene, admin, audits):
    audits.side_effect = OSError("full audit disk")
    with pytest.raises(OSError):
        await QuotaService(db, admin, {}).configure("USER", scene[0].id, 1, "cap")
    await db.rollback()
    assert not (await db.scalars(select(QuotaLimit))).all()


async def test_postgres_failed_copy_remains_charged(api, db, scene, clean, admin):
    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("Independent PostgreSQL reservation transaction")
    client, state = api
    state["actor"] = scene[0]
    row, _, storage = clean
    await QuotaService(db, admin, {}).configure("USER", scene[0].id, 10, "cap")
    app.dependency_overrides[require_csrf] = lambda: None
    with (
        patch("app.api.v1.documents.create_storage", return_value=storage),
        patch(
            "app.documents.service.write_audit_event",
            new=AsyncMock(side_effect=OSError("audit full")),
        ),
    ):
        response = await client.post(
            f"/api/v1/documents/{row.id}/copy", json={"parent_id": str(scene[2].id)}
        )
    assert response.status_code == 503
    reservations = (await db.scalars(select(StorageReservation))).all()
    assert len(reservations) == 1 and reservations[0].size == 5
    assert await QuotaService(db, admin, {}).usage("USER", scene[0].id) == 10
    with pytest.raises(HTTPException):
        await UploadService(db, storage).new_version(
            scene[0], row.id, "hello.txt", io.BytesIO(b"1"), {}
        )


async def test_postgres_concurrent_quota_reservations():
    import asyncio
    import uuid

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.document import DocumentVersion
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User
    from tests.test_upload import MemoryStorage

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL advisory locks and durable journal")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, cid, did, sid = [uuid.uuid4() for _ in range(4)]
    document_id = None
    storage = MemoryStorage()
    try:
        async with factory() as db:
            actor = User(id=uid, authentik_sub=str(uid), username="quota-test", display_name="test")
            db.add_all([actor, Company(id=cid, name=str(cid))])
            await db.flush()
            db.add(Department(id=did, company_id=cid, name="test"))
            await db.flush()
            db.add(
                Resource(
                    id=sid, resource_type="SPACE", name="test", owner_user_id=uid, department_id=did
                )
            )
            await db.commit()
            first = await UploadService(db, storage).create(
                actor, sid, "file.txt", io.BytesIO(b"12345"), {}
            )
            document_id = first.document_id
            scanner = Mock()
            scanner.scan.return_value = True
            await UploadService(db, storage).scan_one(scanner)
            db.add(QuotaLimit(subject_type="USER", subject_id=uid, limit_bytes=6))
            await db.commit()

        async def upload():
            async with factory() as db:
                actor = await db.get(User, uid)
                try:
                    await UploadService(db, storage).new_version(
                        actor, document_id, "file.txt", io.BytesIO(b"1"), {}
                    )
                    return True
                except HTTPException as error:
                    assert error.status_code == 413
                    await db.rollback()
                    return False

        assert sum(await asyncio.gather(*(upload() for _ in range(5)))) == 1
        async with factory() as db:
            actor = await db.get(User, uid)
            assert await QuotaService(db, actor, {}).usage("USER", uid) == 6
            incidents = (
                await db.scalars(select(QuotaIncident).where(QuotaIncident.actor_id == uid))
            ).all()
            assert len(incidents) == 4
    finally:
        async with factory() as db:
            for model, condition in [
                (StorageReservation, StorageReservation.owner_id == uid),
                (QuotaIncident, QuotaIncident.actor_id == uid),
                (QuotaLimit, QuotaLimit.subject_id == uid),
                (DocumentVersion, DocumentVersion.document_id == document_id),
                (Resource, Resource.id == document_id),
                (Resource, Resource.id == sid),
                (Department, Department.id == did),
                (Company, Company.id == cid),
                (User, User.id == uid),
            ]:
                await db.execute(delete(model).where(condition))
            await db.commit()
        await engine.dispose()


async def test_office_save_obeys_quota(db, scene, office, admin):
    from app.models.office import OfficeSave
    from app.office.templates import blank

    service, version, _, storage, config, session_id = office
    await QuotaService(db, admin, {}).configure("USER", scene[0].id, version.size, "cap")
    before = dict(storage.objects)
    payload = {
        "key": config["config"]["document"]["key"], "status": 6, "filetype": "docx",
        "users": [str(scene[0].id)],
        "url": "http://onlyoffice/cache/files/key/output.docx",
    }

    async def download(url, source):
        source.write(blank("docx").getvalue())
        source.seek(0)

    with patch.object(service, "download", new=download), pytest.raises(HTTPException) as error:
        await service.callback(session_id, payload, storage)
    assert error.value.status_code == 413 and storage.objects == before
    assert not (await db.scalars(select(OfficeSave))).all()


async def test_zero_quota_blocks_upload(db, scene, clean, admin):
    row, _, storage = clean
    await QuotaService(db, admin, {}).configure("USER", scene[0].id, 0, "disabled writes")
    before = dict(storage.objects)
    with pytest.raises(HTTPException) as error:
        await UploadService(db, storage).new_version(
            scene[0], row.id, "hello.txt", io.BytesIO(b"1"), {}
        )
    assert error.value.status_code == 413 and storage.objects == before
