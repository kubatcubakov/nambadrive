import io
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.auth.dependencies import require_csrf
from app.documents.service import DocumentService
from app.documents.upload import UploadService
from app.documents.versions import VersionService
from app.main import app
from app.models.document import DocumentVersion
from tests.test_authorization import scene as authorization_scene
from tests.test_documents import api as documents_api
from tests.test_documents import clean as clean_document

scene = authorization_scene
clean = clean_document
api = documents_api


@pytest.fixture(autouse=True)
def audit():
    with (
        patch("app.documents.upload.write_audit_event", new=AsyncMock()),
        patch("app.documents.service.write_audit_event", new=AsyncMock()),
    ):
        yield


async def new(db, scene, clean, value):
    row, _, storage = clean
    return await UploadService(db, storage).new_version(
        scene[0], row.id, "hello.txt", io.BytesIO(value), {}
    )


async def test_pending_new_version_does_not_replace_current(db, scene, clean):
    row, first, storage = clean
    pending = await new(db, scene, clean, b"new content")
    assert first.is_current and not pending.is_current
    assert (await DocumentService(db, scene[0], {}).current(row.id)).id == first.id
    scanner = Mock()
    scanner.scan.return_value = False
    await UploadService(db, storage).scan_one(scanner)
    assert pending.status == "INFECTED" and first.is_current


@pytest.mark.parametrize("protected", [False, True])
async def test_current_plus_two_and_hold_retention(db, scene, clean, protected):
    row, first, storage = clean
    if protected:
        row.legal_hold = True
        row.retention_until = datetime.now(UTC) + timedelta(days=365)
        await db.commit()
    scanner = Mock()
    scanner.scan.return_value = True
    versions = [first]
    for number in range(4):
        versions.append(await new(db, scene, clean, str(number).encode()))
        await UploadService(db, storage).scan_one(scanner)
    history = await VersionService(db, scene[0], {}).history(row.id)
    assert len(history) == (5 if protected else 3)
    assert sum(v.is_current for v in versions) == 1
    assert versions[-1].is_current
    if not protected:
        assert versions[0].prune_after is not None
        assert len(storage.objects) == 10  # no physical purge in version service


async def test_out_of_order_scans_do_not_roll_current_back(db, scene, clean):
    row, _, storage = clean
    older = await new(db, scene, clean, b"older")
    newest = await new(db, scene, clean, b"newest")
    older.retry_after = datetime.now(UTC) + timedelta(minutes=5)
    await db.commit()
    scanner = Mock()
    scanner.scan.return_value = True
    await UploadService(db, storage).scan_one(scanner)
    assert newest.is_current
    older.retry_after = None
    await db.commit()
    await UploadService(db, storage).scan_one(scanner)
    assert newest.is_current and not older.is_current
    assert (await DocumentService(db, scene[0], {}).current(row.id)).id == newest.id


async def test_restore_creates_immutable_new_version(db, scene, clean):
    row, first, storage = clean
    second = await new(db, scene, clean, b"second")
    scanner = Mock()
    scanner.scan.return_value = True
    await UploadService(db, storage).scan_one(scanner)
    restored = await VersionService(db, scene[0], {}).restore(row.id, first.id, storage)
    assert restored.id not in {first.id, second.id}
    assert restored.sequence_no == 3 and restored.is_current
    assert restored.sha256 == first.sha256
    assert not first.is_current and not second.is_current


async def test_version_routes_deny_idor_and_csrf(api, scene, clean):
    client, state = api
    row, first, storage = clean
    path = f"/api/v1/documents/{row.id}/versions"
    with patch("app.api.v1.documents.create_storage", return_value=storage):
        assert (await client.get(path)).status_code == 403
        assert (await client.post(path + "?filename=hello.txt", content=b"new")).status_code == 403
        app.dependency_overrides[require_csrf] = lambda: None
        assert (await client.post(path + "?filename=hello.txt", content=b"new")).status_code == 403
        assert (await client.post(path + f"/{first.id}/restore")).status_code == 403
        state["actor"] = scene[0]
        assert len((await client.get(path)).json()["data"]) == 1
        assert (await client.post(path + "?filename=hello.txt", content=b"new")).status_code == 202


@pytest.mark.skipif(
    os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1", reason="PostgreSQL trigger required"
)
async def test_postgres_immutable_version_metadata(db, clean):
    _, first, _ = clean
    version_id = first.id
    for field, value in [
        ("sha256", "'" + "a" * 64 + "'"),
        ("filename", "'changed.txt'"),
        ("status", "'PENDING'"),
    ]:
        async with db.begin_nested() as transaction:
            with pytest.raises(DBAPIError):
                await db.execute(
                    text(f"UPDATE document_versions SET {field}={value} WHERE id=:id"),
                    {"id": version_id},
                )
            await transaction.rollback()
    assert (
        await db.scalar(select(DocumentVersion.sha256).where(DocumentVersion.id == version_id))
    ) != "a" * 64


@pytest.mark.skipif(
    os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1", reason="PostgreSQL row locks required"
)
async def test_postgres_concurrent_new_versions():
    import asyncio
    import uuid

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User
    from tests.test_upload import MemoryStorage

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, cid, did, sid = [uuid.uuid4() for _ in range(4)]
    document_id = None
    storage = MemoryStorage()
    try:
        async with factory() as session:
            actor = User(
                id=uid,
                authentik_sub=str(uid),
                username="version-test",
                display_name="test",
                enabled=True,
            )
            session.add_all([actor, Company(id=cid, name=str(cid))])
            await session.flush()
            session.add(Department(id=did, company_id=cid, name="test"))
            await session.flush()
            session.add(
                Resource(
                    id=sid, resource_type="SPACE", name="test", owner_user_id=uid, department_id=did
                )
            )
            await session.commit()
            first = await UploadService(session, storage).create(
                actor, sid, "test.txt", io.BytesIO(b"first"), {}
            )
            document_id = first.document_id
            scanner = Mock()
            scanner.scan.return_value = True
            await UploadService(session, storage).scan_one(scanner)

        async def upload(number):
            async with factory() as session:
                actor = await session.get(User, uid)
                version = await UploadService(session, storage).new_version(
                    actor, document_id, "test.txt", io.BytesIO(str(number).encode()), {}
                )
                return version.sequence_no

        numbers = await asyncio.gather(*(upload(n) for n in range(5)))
        assert sorted(numbers) == [2, 3, 4, 5, 6]

        async def scan():
            async with factory() as session:
                scanner = Mock()
                scanner.scan.return_value = True
                return await UploadService(session, storage).scan_one(scanner)

        assert all(await asyncio.gather(*(scan() for _ in range(5))))
        async with factory() as session:
            versions = list(
                (
                    await session.scalars(
                        select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                    )
                ).all()
            )
            assert len(versions) == 6
            assert [v.sequence_no for v in versions if v.is_current] == [6]
    finally:
        async with factory() as session:
            if document_id:
                await session.execute(
                    delete(DocumentVersion).where(DocumentVersion.document_id == document_id)
                )
                await session.execute(delete(Resource).where(Resource.id == document_id))
            await session.execute(delete(Resource).where(Resource.id == sid))
            await session.execute(delete(Department).where(Department.id == did))
            await session.execute(delete(Company).where(Company.id == cid))
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
        await engine.dispose()
