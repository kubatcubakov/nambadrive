"""Verified, raster-only preview preparation shared by authenticated/capability APIs."""

import subprocess  # nosec B404
import sys
import tempfile

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.documents.service import read_verified
from app.models.document import DocumentVersion
from app.storage.seaweed import SeaweedStorage


async def raster_preview(storage: SeaweedStorage, version: DocumentVersion, page: int) -> bytes:
    if version.mime_type not in {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/plain",
        "text/csv",
        "application/json",
        "application/xml",
    }:
        raise HTTPException(415, "Preview unavailable for this format")
    with tempfile.NamedTemporaryFile() as source:
        await run_in_threadpool(read_verified, storage, version, source.file)
        source.flush()

        def render() -> bytes:
            try:
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "app.documents.preview",
                        source.name,
                        version.mime_type,
                        str(page),
                    ],
                    capture_output=True,
                    timeout=30,
                    check=True,
                ).stdout  # nosec B603
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                raise HTTPException(422, "Preview could not be generated") from None

        return await run_in_threadpool(render)
