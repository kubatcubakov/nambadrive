import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.main import app
from app.models.acl import HardPolicy
from app.models.share import ExternalShare
from app.shares.security import limit_attempts, password_hash, token_hash, verify_password
from app.shares.service import ShareService
from tests.test_authorization import acl
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture

api, clean, scene = api_fixture, clean_fixture, scene_fixture


@pytest.fixture(autouse=True)
def audit():
    with patch("app.shares.service.write_audit_event", new=AsyncMock()) as event:
        yield event


@pytest.fixture
async def public(db, scene, clean):
    row, version, storage = clean
    for resource in [row, scene[2], scene[3]]:
        resource.classification = "PUBLIC"
    await db.commit()
    return row, version, storage


async def test_share_management_requires_authorization_and_csrf(api, public, scene, db):
    client, state = api
    row, _, _ = public
    path = f"/api/v1/shares/documents/{row.id}"
    state["actor"] = scene[0]
    assert (await client.post(path, json={})).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    state["actor"] = scene[1]
    assert (await client.get(path)).status_code == 403
    assert (await client.post(path, json={})).status_code == 403
    assert (await client.delete(path + "/" + str(uuid.uuid4()))).status_code == 403
    state["actor"] = scene[0]
    for payload in [
        {"days": 31},
        {"days": 0},
        {"password": "short"},
        {"max_views": 0},
        {"allow_view": False, "allow_download": False},
    ]:
        assert (await client.post(path, json=payload)).status_code == 422
    response = await client.post(path, json={})
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    token = data["path"].split("#")[1]
    stored = await db.get(ExternalShare, uuid.UUID(data["id"]))
    assert len(token) == 43 and token not in repr(stored.__dict__)
    assert stored.token_hash == token_hash(token)
    assert stored.expires_at - stored.created_at == timedelta(days=7)
    listed = await client.get(path)
    assert (
        token not in listed.text
        and "token_hash" not in listed.text
        and "password_hash" not in listed.text
    )
    assert (await client.delete(path + "/" + data["id"])).status_code == 200
    assert stored.revoked_at is not None


async def test_external_share_requires_entire_public_chain(db, scene, clean):
    row, _, _ = clean
    service = ShareService(db, {})
    for classification in ["INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"]:
        row.classification = classification
        await db.commit()
        with pytest.raises(HTTPException):
            await service.create(scene[0], row.id)
    row.classification = "PUBLIC"
    await db.commit()
    with pytest.raises(HTTPException):
        await service.create(scene[0], row.id)  # parent remains INTERNAL


async def test_anonymous_preview_download_password_and_max_views(api, db, scene, public):
    client, _ = api
    row, _, storage = public
    share, token = await ShareService(db, {}).create(
        scene[0], row.id, password="test-password-long", max_views=1
    )
    with (
        patch("app.api.v1.shares.limit_attempts", new=AsyncMock()),
        patch("app.api.v1.shares.create_storage", return_value=storage),
    ):
        for payload in [
            {"token": token},
            {"token": token, "password": "wrong"},
            {"token": token, "password": "test-password-long", "action": "download"},
        ]:
            response = await client.post("/api/v1/shares/access", json=payload)
            assert response.status_code == 403 and share.views == 0
        response = await client.post(
            "/api/v1/shares/access", json={"token": token, "password": "test-password-long"}
        )
        assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
        assert response.headers["Cache-Control"] == "no-store" and share.views == 1
        response = await client.post(
            "/api/v1/shares/access", json={"token": token, "password": "test-password-long"}
        )
        assert response.status_code == 403
    assert token not in share.password_hash and "test-password-long" not in share.password_hash


async def test_download_only_share(api, db, scene, public):
    client, _ = api
    row, _, storage = public
    _, token = await ShareService(db, {}).create(
        scene[0], row.id, allow_view=False, allow_download=True
    )
    with (
        patch("app.api.v1.shares.limit_attempts", new=AsyncMock()),
        patch("app.api.v1.shares.create_storage", return_value=storage),
    ):
        assert (
            await client.post("/api/v1/shares/access", json={"token": token})
        ).status_code == 403
        result = await client.post(
            "/api/v1/shares/access", json={"token": token, "action": "download"}
        )
        assert result.status_code == 200 and result.content == b"hello"
        assert "attachment" in result.headers["Content-Disposition"]


@pytest.mark.parametrize(
    "block",
    [
        "expired",
        "future",
        "too_long",
        "revoked",
        "disabled",
        "trash",
        "parent_private",
        "hard_share",
        "hard_preview",
        "no_password",
        "wrong_permission",
        "quota",
    ],
)
async def test_central_capability_rechecks(db, scene, public, block):
    row, _, _ = public
    share, token = await ShareService(db, {}).create(scene[0], row.id)
    password_valid, permission = True, "PREVIEW"
    if block == "expired":
        share.created_at = datetime.now(UTC) - timedelta(days=10)
        share.expires_at = datetime.now(UTC) - timedelta(days=1)
    elif block == "future":
        share.created_at = datetime.now(UTC) + timedelta(days=1)
    elif block == "too_long":
        # Reject malformed grants without storing invalid PostgreSQL data.
        share.expires_at = datetime.now(UTC) + timedelta(days=31)
    elif block == "revoked":
        share.revoked_at = datetime.now(UTC)
    elif block == "disabled":
        scene[0].enabled = False
    elif block == "trash":
        row.state, row.deleted_at = "TRASH", datetime.now(UTC)
    elif block == "parent_private":
        scene[3].classification = "CONFIDENTIAL"
    elif block.startswith("hard_"):
        db.add(
            HardPolicy(
                resource_id=row.id,
                permission_id="EXTERNAL_SHARE" if block == "hard_share" else "PREVIEW",
                reason="blocked",
            )
        )
    elif block == "no_password":
        password_valid = False
    elif block == "wrong_permission":
        permission = "EDIT"
    else:
        share.max_views, share.views = 1, 1
    if block != "too_long":
        await db.flush()
    with db.no_autoflush:
        decision = await AuthorizationService().authorize_share(
            db, share, permission, password_valid=password_valid
        )
    assert not decision.allowed


async def test_creator_acl_revocation_disables_share(db, scene, public):
    row, _, _ = public
    grants = []
    for permission in ["VIEW", "PREVIEW", "SHARE", "EXTERNAL_SHARE"]:
        grants.append(
            await acl(
                db,
                scene,
                resource=row,
                permission=permission,
                valid_from=datetime.now(UTC) - timedelta(days=1),
            )
        )
    service = ShareService(db, {})
    share, token = await service.create(scene[1], row.id)
    assert (await service.resolve(token, None, "PREVIEW"))[0].id == share.id
    grants[-1].revoked_at = datetime.now(UTC)
    await db.commit()
    with pytest.raises(HTTPException):
        await service.resolve(token, None, "PREVIEW")


async def test_critical_share_audit_rollback(db, scene, public, audit):
    row, _, _ = public
    service = ShareService(db, {})
    audit.side_effect = OSError("full audit disk")
    with pytest.raises(OSError):
        await service.create(scene[0], row.id)
    await db.rollback()
    assert not (await db.scalars(select(ExternalShare))).all()
    for item in list(db.identity_map.values()):
        await db.refresh(item)
    audit.side_effect = None
    share, token = await service.create(scene[0], row.id)
    audit.side_effect = OSError("full audit disk")
    with pytest.raises(OSError):
        await service.revoke(scene[0], row.id, share.id)
    await db.rollback()
    await db.refresh(share)
    assert share.revoked_at is None
    assert token not in repr(audit.call_args_list)


async def test_rate_limits_and_failure_closed():
    from redis.exceptions import ConnectionError

    with patch("app.shares.security.redis_client.eval", new=AsyncMock(return_value=1)) as evaluate:
        await limit_attempts("127.0.0.1", token_hash("test"))
        assert evaluate.await_count == 3
        assert "127.0.0.1" not in repr(evaluate.call_args_list)
        evaluate.return_value = 121
        with pytest.raises(HTTPException) as error:
            await limit_attempts("127.0.0.1", token_hash("test"))
        assert error.value.status_code == 429
        evaluate.side_effect = ConnectionError("private redis information")
        with pytest.raises(HTTPException) as error:
            await limit_attempts("127.0.0.1", token_hash("test"))
        assert error.value.status_code == 503 and "private" not in error.value.detail


def test_password_kdf_salted_and_malformed_closed():
    first, second = password_hash("long password"), password_hash("long password")
    assert first != second and verify_password("long password", first)
    assert not verify_password("wrong", first)
    assert not verify_password("x", "broken")
    assert not verify_password("x", first.replace("600000", "1"))


async def test_internal_link_does_not_grant_access(api, db, scene, public):
    client, state = api
    row, _, _ = public
    state["actor"] = scene[0]
    app.dependency_overrides[require_csrf] = lambda: None
    with patch("app.documents.service.write_audit_event", new=AsyncMock()):
        result = await client.post(f"/api/v1/shares/internal/{row.id}")
    assert result.status_code == 200 and str(row.id) in result.json()["data"]["path"]
    state["actor"] = scene[1]
    assert (await client.get(f"/api/v1/documents/{row.id}")).status_code == 403
    assert (await client.post(f"/api/v1/shares/internal/{row.id}")).status_code == 403


async def test_anonymous_audit_failure_returns_no_bytes(api, db, scene, public, audit):
    client, _ = api
    row, _, storage = public
    share, token = await ShareService(db, {}).create(scene[0], row.id, allow_download=True)
    audit.side_effect = OSError("audit full")
    with (
        patch("app.api.v1.shares.limit_attempts", new=AsyncMock()),
        patch("app.api.v1.shares.create_storage", return_value=storage),
    ):
        result = await client.post(
            "/api/v1/shares/access", json={"token": token, "action": "download"}
        )
    assert result.status_code == 503 and b"hello" not in result.content
    assert share.views == 0


async def test_postgres_concurrent_last_share_view():
    import asyncio
    import os

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.document import DocumentVersion
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("Requires PostgreSQL row locks")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, cid, did, sid, rid = [uuid.uuid4() for _ in range(5)]
    try:
        async with factory() as session:
            actor = User(id=uid, authentik_sub=str(uid), username="share-test", display_name="test")
            session.add_all([actor, Company(id=cid, name=str(cid))])
            await session.flush()
            session.add(Department(id=did, company_id=cid, name="test"))
            await session.flush()
            session.add(
                Resource(
                    id=sid,
                    resource_type="SPACE",
                    name="test",
                    owner_user_id=uid,
                    department_id=did,
                    classification="PUBLIC",
                )
            )
            await session.flush()
            session.add(
                Resource(
                    id=rid,
                    resource_type="DOCUMENT",
                    parent_id=sid,
                    name="test.txt",
                    owner_user_id=uid,
                    department_id=did,
                    classification="PUBLIC",
                )
            )
            await session.flush()
            session.add(
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
            await session.commit()
            share, token = await ShareService(session, {}).create(actor, rid, max_views=1)
            share_id = share.id

        async def consume():
            async with factory() as session:
                service = ShareService(session, {})
                try:
                    share, _ = await service.resolve(token, None, "PREVIEW")
                    await service.consume(share, "PREVIEW")
                    return True
                except HTTPException:
                    await session.rollback()
                    return False

        results = await asyncio.gather(*(consume() for _ in range(5)))
        assert sum(results) == 1
        async with factory() as session:
            assert (await session.get(ExternalShare, share_id)).views == 1
    finally:
        async with factory() as session:
            for model, condition in [
                (ExternalShare, ExternalShare.document_id == rid),
                (DocumentVersion, DocumentVersion.document_id == rid),
                (Resource, Resource.id == rid),
                (Resource, Resource.id == sid),
                (Department, Department.id == did),
                (Company, Company.id == cid),
                (User, User.id == uid),
            ]:
                await session.execute(delete(model).where(condition))
            await session.commit()
        await engine.dispose()


async def test_real_redis_concurrent_password_attempt_limit():
    import asyncio
    import os

    from redis.asyncio import Redis

    url = os.environ.get("NAMBADRIVE_TEST_REDIS_URL")
    if not url:
        pytest.skip("Requires disposable Redis")
    client = Redis.from_url(url, decode_responses=True)
    ip = str(uuid.uuid4())
    digest = token_hash(str(uuid.uuid4()))
    keys = ["share-rate:all", "share-rate:ip:" + token_hash(ip), "share-rate:token:" + digest]
    try:

        async def attempt():
            try:
                await limit_attempts(ip, digest)
                return True
            except HTTPException as error:
                assert error.status_code == 429
                return False

        with patch("app.shares.security.redis_client", client):
            assert sum(await asyncio.gather(*(attempt() for _ in range(20)))) == 10
        assert 0 < await client.ttl(keys[-1]) <= 60
    finally:
        await client.delete(*keys)
        await client.aclose()
