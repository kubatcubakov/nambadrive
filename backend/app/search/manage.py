"""Operator-only index provisioning / checkpoint rebuild; no document or ACL mutation."""

import argparse
import asyncio

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.search import SearchCheckpoint
from app.search.clients import OpenSearch


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["initialize", "rebuild"])
    args = parser.parse_args()
    if args.action == "initialize":
        OpenSearch(get_settings()).initialize()
    else:
        async with SessionLocal() as db:
            await db.execute(delete(SearchCheckpoint))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
