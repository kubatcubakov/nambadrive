import hashlib
import io
import zipfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.authorization.service import AuthorizationService
from app.documents.antivirus import ClamAV, ScanUnavailable
from app.documents.upload import UploadService
from app.documents.validation import filename, validate
from app.models.document import DocumentVersion
from app.models.resource import Resource
from app.storage.seaweed import Area, ObjectExists, ObjectInfo, StorageError
from tests.test_authorization import scene as authorization_scene

scene = authorization_scene


class MemoryStorage:
    max_bytes = 1024 * 1024

    def __init__(self):
        self.objects = {}

    def put(self, key, source, area=Area.QUARANTINE):
        if (area, str(key)) in self.objects:
            raise ObjectExists()
        source.seek(0)
        data = source.read()
        self.objects[area, str(key)] = data
        return ObjectInfo(len(data), hashlib.sha256(data).hexdigest())

    def read(self, key, area=Area.DATA):
        yield self.objects[area, str(key)]

    def stat(self, key, area=Area.DATA):
        data = self.objects[area, str(key)]
        return ObjectInfo(len(data), hashlib.sha256(data).hexdigest())


@pytest.fixture
def storage():
    return MemoryStorage()


@pytest.fixture(autouse=True)
def audit():
    with patch("app.documents.upload.write_audit_event", new=AsyncMock()) as event:
        yield event


@pytest.mark.parametrize(
    "name", ["../a.txt", "a\\b.txt", ".txt", "a.exe", "a\x00.txt", "a\u202etxt", " a.txt", "a:txt"]
)
def test_unsafe_filename(name):
    with pytest.raises(ValueError):
        filename(name)


@pytest.mark.parametrize(
    "name,data",
    [
        ("x.json", b"{"),
        ("x.xml", b"<!DOCTYPE x><x/>"),
        ("x.pdf", b"not a pdf"),
        ("x.txt", b"\x00"),
        ("x.png", b"not png"),
        ("x.txt", b""),
    ],
)
def test_invalid_content(name, data):
    with pytest.raises(ValueError):
        validate(io.BytesIO(data), name, 100000)


def archive(items, compression=zipfile.ZIP_STORED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as z:
        for name, data in items:
            z.writestr(name, data)
    return out


@pytest.mark.parametrize("items", [[("../evil", b"x")], [("x", b"PK\x03\x04nested")]])
def test_unsafe_zip(items):
    with pytest.raises(ValueError):
        validate(archive(items), "x.zip", 100000)


def test_zip_bomb_and_office_spoof():
    with pytest.raises(ValueError, match="expansion"):
        validate(archive([("bomb", b"0" * 100000)], zipfile.ZIP_DEFLATED), "x.zip", 200000)
    with pytest.raises(ValueError, match="office"):
        validate(archive([("text", b"hello")]), "x.docx", 10000)
    assert validate(archive([("text", b"hello")]), "x.zip", 10000) == "application/zip"


@pytest.mark.parametrize(
    "reply,expected",
    [
        (b"stream: OK\0", True),
        (b"stream: Eicar FOUND\0", False),
        (b"stream: size ERROR\0", None),
        (b"OK", None),
        (b"", None),
    ],
)
def test_clam_protocol_fail_closed(reply, expected):
    connection = Mock()
    connection.recv.side_effect = [reply, b""]
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    with patch("socket.create_connection", return_value=connection):
        if expected is None:
            with pytest.raises(ScanUnavailable):
                ClamAV("localhost", 3310, 1024).scan(io.BytesIO(b"test"))
        else:
            assert ClamAV("localhost", 3310, 1024).scan(io.BytesIO(b"test")) is expected
        assert connection.sendall.call_args_list[0].args == (b"zINSTREAM\0",)


async def test_upload_default_deny_and_clean_promotion(db, scene, storage):
    owner, outsider, _, folder, *_ = scene
    service = UploadService(db, storage)
    with pytest.raises(HTTPException):
        await service.create(outsider, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    version = await service.create(owner, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    document = await db.get(Resource, version.document_id)
    assert document.state == "QUARANTINED"
    assert not (await AuthorizationService().authorize(db, owner, "VIEW", document.id)).allowed
    scanner = Mock()
    scanner.scan.return_value = True
    assert await service.scan_one(scanner)
    assert document.state == "ACTIVE" and version.status == "CLEAN"
    assert len(storage.objects) == 2
    assert not await service.scan_one(scanner)


@pytest.mark.parametrize("verdict", [False, ScanUnavailable("offline"), StorageError("offline")])
async def test_malware_and_outages_never_activate(db, scene, storage, verdict):
    owner, _, _, folder, *_ = scene
    service = UploadService(db, storage)
    version = await service.create(owner, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    document = await db.get(Resource, version.document_id)
    scanner = Mock()
    if isinstance(verdict, Exception):
        scanner.scan.side_effect = verdict
        with pytest.raises(type(verdict)):
            await service.scan_one(scanner)
    else:
        scanner.scan.return_value = verdict
        await service.scan_one(scanner)
        assert version.status == "INFECTED"
    await db.refresh(document)
    assert document.state == "QUARANTINED"
    assert len(storage.objects) == 1


async def test_checksum_mismatch_keeps_quarantine(db, scene, storage):
    owner, _, _, folder, *_ = scene
    service = UploadService(db, storage)
    version = await service.create(owner, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    storage.objects[next(iter(storage.objects))] = b"tampered"
    with pytest.raises(StorageError):
        await service.scan_one(Mock())
    assert version.status == "PENDING"


async def test_revoked_actor_cannot_promote(db, scene, storage):
    owner, _, _, folder, *_ = scene
    service = UploadService(db, storage)
    version = await service.create(owner, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    owner.enabled = False
    await db.commit()
    scanner = Mock()
    await service.scan_one(scanner)
    assert version.status == "REJECTED"
    scanner.scan.assert_not_called()


async def test_audit_failure_rolls_back_promotion_and_retry_reconciles(db, scene, storage, audit):
    owner, _, _, folder, *_ = scene
    service = UploadService(db, storage)
    version = await service.create(owner, folder.id, "x.txt", io.BytesIO(b"hello"), {})
    version_id, document_id = version.id, version.document_id
    scanner = Mock()
    scanner.scan.return_value = True
    audit.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await service.scan_one(scanner)
    await db.rollback()
    version = await db.get(DocumentVersion, version_id)
    document = await db.get(Resource, document_id)
    assert version.status == "PENDING" and document.state == "QUARANTINED"
    audit.side_effect = None
    version.retry_after = None
    await db.commit()
    assert await service.scan_one(scanner)
    assert version.status == "CLEAN"
    assert len(storage.objects) == 2


async def test_upload_api_csrf_authorization_and_no_storage_url(db, scene, storage):
    from httpx import ASGITransport, AsyncClient

    from app.auth.dependencies import current_user, require_csrf
    from app.core.database import get_db
    from app.main import app

    actor = scene[1]

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[current_user] = lambda: actor
    try:
        with patch("app.api.v1.documents.create_storage", return_value=storage):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/api/v1/documents/upload?parent_id={scene[3].id}&filename=x.txt"
                assert (await client.post(path, content=b"hello")).status_code == 403
                app.dependency_overrides[require_csrf] = lambda: None
                assert (await client.post(path, content=b"hello")).status_code == 403
                actor = scene[0]
                response = await client.post(path, content=b"hello")
                assert response.status_code == 202
                assert response.json()["data"]["status"] == "PENDING"
                assert "url" not in response.text.lower() and "secret" not in response.text.lower()
                document = response.json()["data"]["document_id"]
                assert (await client.get("/api/v1/resources/" + document)).status_code == 403
    finally:
        app.dependency_overrides.clear()
