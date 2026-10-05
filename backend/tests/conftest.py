import os

import pytest_asyncio
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import Base
from app.models.acl import Permission, Role, RolePermission


@pytest_asyncio.fixture
async def db():
    postgres = os.environ.get("NAMBADRIVE_TEST_POSTGRES") == "1"
    engine = create_async_engine(
        get_settings().database_url if postgres else "sqlite+aiosqlite:///:memory:"
    )
    if postgres:
        # CI migrations create schema/triggers. Each test rolls back its outer transaction.
        async with engine.connect() as connection:
            transaction = await connection.begin()
            for model in (RolePermission, Role, Permission):
                await connection.execute(delete(model))
            async with async_sessionmaker(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )() as session:
                yield session
            await transaction.rollback()
    else:

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    await engine.dispose()
