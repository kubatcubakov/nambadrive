from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService, utc
from app.documents.service import DocumentService
from app.governance.cleanup import CleanupWorker
from app.governance.service import GovernanceService
from app.main import app
from app.models.governance import LegalHoldEvent, RetentionPolicy
from app.storage.seaweed import Area, StorageError
from tests.test_authorization import binding
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_organization import user

api, clean, scene = api_fixture, clean_fixture, scene_fixture


@pytest.fixture(autouse=True)
def audits():
    with (
        patch("app.governance.service.write_audit_event", new=AsyncMock()) as policy,
        patch("app.governance.cleanup.write_audit_event", new=AsyncMock()) as cleanup,
        patch("app.documents.service.write_audit_event", new=AsyncMock()),
    ):
        yield policy, cleanup


@pytest.fixture
async def admin(db, scene):
    actor = await user(db)
    await binding(db, actor, "SYSTEM_ADMIN", valid_from=datetime.now(UTC) - timedelta(days=1))
    return actor


@pytest.fixture
async def disposable(clean):
    row, version, storage = clean
    storage.deleted = []

    def delete(key, area):
        storage.deleted.append((area, str(key)))
        storage.objects.pop((area, str(key)), None)

    storage.delete = delete
    return row, version, storage


async def test_policy_admin_has_no_implicit_content_and_csrf(api, db, scene, clean, admin):
    client, state = api
    row, _, _ = clean
    body = {"enabled": True, "reason": "litigation"}
    path = f"/api/v1/admin/governance/resources/{row.id}"
    state["actor"] = scene[0]
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put(path + "/hold", json=body)).status_code == 403
    app.dependency_overrides.pop(require_csrf)
    state["actor"] = admin
    assert (await client.put(path + "/hold", json=body)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put(path + "/hold", json=body)).status_code == 200
    response = await client.get(path)
    assert response.status_code == 200 and "name" not in response.json()["data"]
    assert (await client.get(f"/api/v1/documents/{row.id}")).status_code == 403
    assert (await client.post(f"/api/v1/documents/{row.id}/purge")).status_code == 404


async def test_hold_history_and_fail_closed_audit(db, scene, disposable, admin, audits):
    row, version, storage = disposable
    service = GovernanceService(db, admin, {})
    await service.hold(scene[3].id, True, "case opened")
    row.state, row.deleted_at = "TRASH", datetime.now(UTC) - timedelta(days=31)
    await db.commit()
    assert await CleanupWorker(db, storage).process_one()
    assert not storage.deleted
    decision = await AuthorizationService().authorize_cleanup(db, version)
    assert decision.reason == "LEGAL_HOLD"
    audits[0].side_effect = OSError("audit disk full")
    with pytest.raises(OSError):
        await service.hold(scene[3].id, False, "case closed")
    await db.rollback()
    for item in list(db.identity_map.values()):
        await db.refresh(item)
    assert scene[3].legal_hold
    audits[0].side_effect = None
    await service.hold(scene[3].id, False, "case closed")
    events = (await db.scalars(select(LegalHoldEvent))).all()
    assert [event.enabled for event in events] == [True, False]
    version.cleanup_retry_after = None
    await db.commit()
    assert await CleanupWorker(db, storage).process_one()
    assert len(storage.deleted) == 2 and version.purged_at and row.purged_at
    assert not (await AuthorizationService().authorize(db, scene[0], "RESTORE", row.id)).allowed


async def test_retention_materialized_and_not_shortened(db, scene, disposable, admin):
    row, version, storage = disposable
    service = GovernanceService(db, admin, {})
    wrong = await service.create_policy("PDF only", scene[2].id, "pdf", 365, "policy")
    assert version.retention_until is None
    policy = await service.create_policy("Contracts", scene[3].id, "txt", 1826, "five years")
    assert utc(version.retention_until) >= utc(version.created_at) + timedelta(days=1826)
    deadline = version.retention_until
    await service.revoke_policy(policy.id, "new policy for future versions")
    assert version.retention_until == deadline
    row.state, row.deleted_at = "TRASH", datetime.now(UTC) - timedelta(days=31)
    await db.commit()
    assert (await AuthorizationService().authorize_cleanup(db, version)).reason == "RETENTION"
    assert (
        await AuthorizationService().authorize(db, scene[0], "PURGE", row.id)
    ).reason == "RETENTION"
    await CleanupWorker(db, storage).process_one()
    assert not storage.deleted
    assert wrong.revoked_at is None


async def test_retention_audit_failure_rolls_back(db, scene, clean, admin, audits):
    _, version, _ = clean
    audits[0].side_effect = OSError("audit unavailable")
    with pytest.raises(OSError):
        await GovernanceService(db, admin, {}).create_policy("policy", None, None, 365, "reason")
    await db.rollback()
    await db.refresh(version)
    assert version.retention_until is None
    assert not (await db.scalars(select(RetentionPolicy))).all()


async def test_quarantine_copy_cleanup_preserves_verified_data(db, disposable):
    row, version, storage = disposable
    future = datetime.now(UTC) + timedelta(days=31)
    assert await CleanupWorker(db, storage).process_one(future)
    assert len(storage.deleted) == 1 and storage.deleted[0][0] == Area.QUARANTINE
    assert version.purged_at is None and version.quarantine_purged_at and row.purged_at is None
    assert any(area == Area.DATA for area, _ in storage.objects)


async def test_corrupt_data_copy_prevents_quarantine_cleanup(db, disposable):
    _, version, storage = disposable
    for key in storage.objects:
        if key[0] == Area.DATA:
            storage.objects[key] = b"corrupt"
    with pytest.raises(StorageError):
        await CleanupWorker(db, storage).process_one(datetime.now(UTC) + timedelta(days=31))
    assert not storage.deleted
    await db.refresh(version)
    assert version.quarantine_purged_at is None


async def test_cleanup_audit_failure_never_deletes(db, disposable, audits):
    row, version, storage = disposable
    row.state, row.deleted_at = "TRASH", datetime.now(UTC) - timedelta(days=31)
    await db.commit()
    audits[1].side_effect = OSError("audit failed")
    with pytest.raises(OSError):
        await CleanupWorker(db, storage).process_one()
    assert not storage.deleted
    await db.refresh(version)
    assert version.purged_at is None and version.purge_started_at is None


async def test_partial_purge_retry_cannot_be_restored(db, scene, disposable):
    row, version, storage = disposable
    row.state, row.deleted_at = "TRASH", datetime.now(UTC) - timedelta(days=31)
    await db.commit()
    original = storage.delete

    def fail_second(key, area):
        if area == Area.QUARANTINE:
            raise StorageError("outage")
        original(key, area)

    storage.delete = fail_second
    with pytest.raises(StorageError):
        await CleanupWorker(db, storage).process_one()
    for item in list(db.identity_map.values()):
        await db.refresh(item)
    assert version.purge_started_at and row.purge_started_at and not version.purged_at
    with pytest.raises(HTTPException):
        await DocumentService(db, scene[0], {}).restore(row.id)
    storage.delete = original
    version.cleanup_retry_after = None
    await db.commit()
    assert await CleanupWorker(db, storage).process_one()
    assert version.purged_at and not storage.objects


@pytest.mark.parametrize("block", ["fresh_trash", "hard_policy", "hold", "retention"])
async def test_no_cleanup_bypass(db, scene, disposable, block):
    from app.models.acl import HardPolicy

    row, version, storage = disposable
    row.state, row.deleted_at = "TRASH", datetime.now(UTC) - timedelta(days=31)
    if block == "fresh_trash":
        row.deleted_at = datetime.now(UTC)
    elif block == "hard_policy":
        db.add(HardPolicy(resource_id=scene[2].id, permission_id="PURGE", reason="stop"))
    elif block == "hold":
        scene[2].legal_hold = True
    else:
        scene[2].retention_until = datetime.now(UTC) + timedelta(days=1)
    await db.commit()
    await CleanupWorker(db, storage).process_one()
    assert not storage.deleted and not version.purged_at


async def test_infected_retained_30_days_and_hold_wins(db, scene, disposable, admin):
    import io
    from unittest.mock import Mock

    from app.documents.upload import UploadService
    from app.models.resource import Resource

    _, _, storage = disposable
    with patch("app.documents.upload.write_audit_event", new=AsyncMock()):
        scanner = Mock()
        scanner.scan.return_value = False
        version = await UploadService(db, storage).create(
            scene[0], scene[3].id, "infected.txt", io.BytesIO(b"test"), {}
        )
        await UploadService(db, storage).scan_one(scanner)
    row = await db.get(Resource, version.document_id)
    assert not (await AuthorizationService().authorize_cleanup(db, version)).allowed
    future = datetime.now(UTC) + timedelta(days=31)
    await GovernanceService(db, admin, {}).hold(row.id, True, "investigation")
    assert (
        await AuthorizationService().authorize_cleanup(db, version, now=future)
    ).reason == "LEGAL_HOLD"
    await GovernanceService(db, admin, {}).hold(row.id, False, "released")
    assert (await AuthorizationService().authorize_cleanup(db, version, now=future)).allowed
    assert not (
        await AuthorizationService().authorize_cleanup(
            db, version, quarantine_only=True, now=future
        )
    ).allowed
    await CleanupWorker(db, storage).process_one(future)
    if version.purged_at is None:
        await CleanupWorker(db, storage).process_one(future)
    assert version.purged_at is not None


async def test_obsolete_version_pruning_and_editor_pin(db, scene, disposable):
    import io
    import uuid
    from unittest.mock import Mock

    from app.documents.upload import UploadService
    from app.models.office import OfficeRoom

    row, old, storage = disposable
    scanner = Mock()
    scanner.scan.return_value = True
    with patch("app.documents.upload.write_audit_event", new=AsyncMock()):
        for number in range(3):
            await UploadService(db, storage).new_version(
                scene[0], row.id, "hello.txt", io.BytesIO(str(number).encode()), {}
            )
            await UploadService(db, storage).scan_one(scanner)
    assert old.prune_after is not None
    old.prune_after = datetime.now(UTC) - timedelta(seconds=1)
    room = OfficeRoom(
        id=uuid.uuid4(),
        document_id=row.id,
        base_version_id=old.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(room)
    await db.commit()
    assert (await AuthorizationService().authorize_cleanup(db, old)).reason == "EDITOR_VERSION_PIN"
    room.closed_at = datetime.now(UTC)
    await db.commit()
    assert (await AuthorizationService().authorize_cleanup(db, old)).allowed
    await CleanupWorker(db, storage).process_one()
    assert old.purged_at and row.purged_at is None
    assert (await AuthorizationService().authorize_cleanup(db, old)).reason == "VERSION_PURGED"


async def test_corrupt_hierarchy_cleanup_denied(db, disposable):
    _, version, _ = disposable
    with patch("app.governance.policy.chain", new=AsyncMock(side_effect=ValueError("cycle"))):
        assert (
            await AuthorizationService().authorize_cleanup(db, version)
        ).reason == "RESOURCE_INVALID"


async def test_resource_retention_extension_only(db, scene, clean, admin):
    row, version, _ = clean
    service = GovernanceService(db, admin, {})
    until = datetime.now(UTC) + timedelta(days=365)
    await service.extend(scene[3].id, until, "legal requirement")
    assert utc(version.retention_until) >= until
    with pytest.raises(ValueError):
        await service.extend(scene[3].id, until - timedelta(days=1), "shorten")
    row.purged_at = datetime.now(UTC)
    await db.commit()
    assert (
        await AuthorizationService().authorize_cleanup(db, version, now=until + timedelta(days=1))
    ).reason == "RESOURCE_INVALID"
    with pytest.raises(HTTPException):
        await service.hold(row.id, True, "too late")


async def test_postgres_deadline_cannot_be_shortened(db, scene, clean, admin):
    import os

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL immutable retention trigger")
    _, version, _ = clean
    await GovernanceService(db, admin, {}).create_policy("keep", None, None, 365, "policy")
    async with db.begin_nested() as transaction:
        with pytest.raises(DBAPIError):
            await db.execute(
                text("UPDATE document_versions SET retention_until = NULL WHERE id = :id"),
                {"id": version.id},
            )
        await transaction.rollback()
    await db.refresh(version)
    assert version.retention_until is not None


async def test_postgres_hold_commit_blocks_waiting_cleanup():
    import asyncio
    import os
    import uuid

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.governance.policy import governance_lock
    from app.models.document import DocumentVersion
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User
    from tests.test_upload import MemoryStorage

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL transaction/advisory locks")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, cid, did, sid, rid = [uuid.uuid4() for _ in range(5)]
    storage = MemoryStorage()
    deleted = []
    storage.delete = lambda key, area: deleted.append((area, str(key)))
    try:
        async with factory() as db:
            db.add(User(id=uid, authentik_sub=str(uid), username="hold-test", display_name="test"))
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
                    state="TRASH",
                    deleted_at=datetime.now(UTC) - timedelta(days=31),
                )
            )
            await db.flush()
            db.add(
                DocumentVersion(
                    document_id=rid,
                    space_id=sid,
                    uploaded_by=uid,
                    filename="test.txt",
                    mime_type="text/plain",
                    size=0,
                    sha256="0" * 64,
                    status="CLEAN",
                    is_current=True,
                )
            )
            await db.commit()

        async def cleanup():
            async with factory() as db:
                return await CleanupWorker(db, storage).process_one()

        async with factory() as policy:
            await governance_lock(policy)
            row = await policy.get(Resource, sid, with_for_update=True)
            row.legal_hold = True
            await policy.flush()
            task = asyncio.create_task(cleanup())
            await asyncio.sleep(0.05)
            assert not task.done()
            await policy.commit()
        assert await task
        assert not deleted
    finally:
        async with factory() as db:
            for model, condition in [
                (DocumentVersion, DocumentVersion.document_id == rid),
                (Resource, Resource.id == rid),
                (Resource, Resource.id == sid),
                (Department, Department.id == did),
                (Company, Company.id == cid),
                (User, User.id == uid),
            ]:
                await db.execute(delete(model).where(condition))
            await db.commit()
        await engine.dispose()
