"""Retry ownership transfers without restoring disabled accounts or old grants."""
import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal
from app.lifecycle.service import LifecycleService


async def main() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await LifecycleService(db, "identity_lifecycle_worker").transfer_pending()
                await db.commit()
        except (SQLAlchemyError, OSError, ValueError):
            logging.warning("Identity transfer deferred: dependency or policy unavailable")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
