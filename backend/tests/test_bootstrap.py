from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.authorization.bootstrap import bootstrap
from app.models.acl import RoleBinding
from app.models.organization import OrganizationAdministrator
from tests.test_authorization import scene as authorization_scene

scene = authorization_scene


@pytest.fixture
async def local_bootstrap(db):
    @asynccontextmanager
    async def local():
        yield db

    original_execute = db.execute

    async def execute_sql(statement, *args, **kwargs):
        if str(statement) == "SELECT pg_advisory_xact_lock(735905)":
            return None
        return await original_execute(statement, *args, **kwargs)

    with (
        patch("app.authorization.bootstrap.SessionLocal", local),
        patch.object(db, "execute", new=execute_sql),
        patch("app.authorization.bootstrap.engine", new=SimpleNamespace(dispose=AsyncMock())),
    ):
        yield


async def test_first_admin_bootstrap_durable_and_single_use(db, scene, local_bootstrap):
    actor = scene[1]
    uid = actor.id
    with patch("app.authorization.bootstrap.write_audit_event", new=AsyncMock()) as audit:
        await bootstrap(uid, "Approved initial administrator")
        assert await db.get(OrganizationAdministrator, uid) is not None
        assert len((await db.scalars(select(RoleBinding))).all()) == 1
        assert audit.await_count == 1
        await db.commit()
        with pytest.raises(ValueError, match="already"):
            await bootstrap(uid, "Repeat initialization")


async def test_bootstrap_audit_outage_rolls_back(db, scene, local_bootstrap):
    uid = scene[1].id
    with patch("app.authorization.bootstrap.write_audit_event", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            await bootstrap(uid, "Approved initial administrator")
    assert await db.get(OrganizationAdministrator, uid) is None
    assert not (await db.scalars(select(RoleBinding))).all()


async def test_bootstrap_disabled_and_empty_reason(db, scene, local_bootstrap):
    actor = scene[1]
    actor.enabled = False
    uid = actor.id
    await db.commit()
    with pytest.raises(ValueError, match="enabled"):
        await bootstrap(uid, "Approved initial administrator")
    with pytest.raises(ValueError, match="reason"):
        await bootstrap(uid, " ")


def test_bootstrap_cli_requires_uuid_and_reason():
    from app.authorization.bootstrap import main

    with patch("sys.argv", ["bootstrap", "--user", "not-a-uuid", "--reason", "setup"]):
        with pytest.raises(SystemExit):
            main()
