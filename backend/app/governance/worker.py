"""Governed internal cleanup: python -m app.governance.worker."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.governance.cleanup import CleanupWorker
from app.storage.seaweed import StorageError, create_storage


async def main() -> None:
    storage = create_storage(get_settings())
    while True:
        try:
            async with SessionLocal() as db:
                processed = await CleanupWorker(db, storage).process_one()
            if not processed:
                await asyncio.sleep(30)
        except (SQLAlchemyError, StorageError, OSError):
            logging.warning("Governed cleanup deferred: dependency unavailable")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
