"""Durable notification producer and outbox consumer: python -m app.notifications.worker."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.notifications.delivery import DeliveryWorker
from app.notifications.service import NotificationService


async def main() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await NotificationService(db).collect()
                for _ in range(100):
                    if not await DeliveryWorker(db, get_settings()).process_one():
                        break
        except (SQLAlchemyError, OSError):
            logging.warning("Notification processing deferred: dependency unavailable")
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
