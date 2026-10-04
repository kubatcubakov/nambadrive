"""Durable indexing worker. Run `python -m app.search.worker`."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.search.clients import OpenSearch, SearchUnavailable, Tika
from app.search.indexer import Indexer
from app.storage.seaweed import StorageError, create_storage


async def main() -> None:
    settings = get_settings()
    storage, tika, index = create_storage(settings), Tika(settings), OpenSearch(settings)
    while True:
        try:
            async with SessionLocal() as db:
                processed = await Indexer(db, storage, tika, index).process_one()
            if not processed:
                await asyncio.sleep(5)
        except (SearchUnavailable, StorageError, SQLAlchemyError, OSError):
            logging.warning("Search indexing deferred: dependency unavailable")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
