"""Quarterly review scheduler. Overdue reviews NEVER revoke access automatically."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.access_reviews.service import ReviewService
from app.core.database import SessionLocal


async def main() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                count = await ReviewService(db, None, {}).create_due()
            if count == 100:
                continue
        except (SQLAlchemyError, OSError):
            logging.warning("Access review scheduler deferred: dependency unavailable")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
