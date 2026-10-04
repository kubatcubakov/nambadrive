"""PostgreSQL-specific invariants; run only against a disposable migrated CI database."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1",
    reason="Requires disposable PostgreSQL 17 CI database",
)


async def test_postgres_tree_trigger_and_emergency_cap():
    engine = create_async_engine(get_settings().database_url)
    uid, company, dept, space, folder, document = [uuid.uuid4() for _ in range(6)]
    now = datetime.now(UTC)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            await conn.execute(
                text(
                    "INSERT INTO users(id,authentik_sub,username,display_name) "
                    "VALUES(:id,:sub,'test','test')"
                ),
                {"id": uid, "sub": str(uid)},
            )
            await conn.execute(
                text("INSERT INTO companies(id,name) VALUES(:id,:name)"),
                {"id": company, "name": str(company)},
            )
            await conn.execute(
                text("INSERT INTO departments(id,company_id,name) VALUES(:id,:company,'D')"),
                {"id": dept, "company": company},
            )
            for rid, kind, parent in [
                (space, "SPACE", None),
                (folder, "FOLDER", space),
                (document, "DOCUMENT", folder),
            ]:
                await conn.execute(
                    text(
                        "INSERT INTO resources(id,resource_type,name,parent_id,"
                        "owner_user_id,department_id) "
                        "VALUES(:id,:kind,'test',:parent,:owner,:dept)"
                    ),
                    {"id": rid, "kind": kind, "parent": parent, "owner": uid, "dept": dept},
                )
            for statement, params in [
                (
                    "UPDATE resources SET parent_id=:document WHERE id=:folder",
                    {"document": document, "folder": folder},
                ),
                (
                    "UPDATE resources SET parent_id=:folder WHERE id=:space",
                    {"folder": folder, "space": space},
                ),
                (
                    "INSERT INTO break_glass_grants(id,user_id,resource_id,permission_id,"
                    "valid_from,valid_until,reason,created_by,audited) "
                    "VALUES(:id,:user,:resource,'VIEW',:start,:end,'test',:user,true)",
                    {
                        "id": uuid.uuid4(),
                        "user": uid,
                        "resource": document,
                        "start": now,
                        "end": now + timedelta(hours=2),
                    },
                ),
            ]:
                savepoint = await conn.begin_nested()
                with pytest.raises(DBAPIError):
                    await conn.execute(text(statement), params)
                await savepoint.rollback()
            await transaction.rollback()
    finally:
        await engine.dispose()
