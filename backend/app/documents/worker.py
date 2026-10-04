"""Run `python -m app.documents.worker`; pending rows survive worker restarts."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.documents.antivirus import ClamAV, ScanUnavailable
from app.documents.upload import UploadService
from app.storage.seaweed import StorageError, create_storage


async def main() -> None:
    settings = get_settings()
    storage = create_storage(settings)
    scanner = ClamAV(settings.clamav_host, settings.clamav_port, settings.upload_max_bytes)
    while True:
        try:
            async with SessionLocal() as db:
                processed = await UploadService(db, storage).scan_one(scanner)
            if not processed:
                await asyncio.sleep(5)
        except (StorageError, ScanUnavailable, SQLAlchemyError, OSError):
            # No exception text: storage/scanner internals must not leak into logs.
            logging.warning("Upload scan deferred: dependency unavailable")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
