from __future__ import annotations

import tempfile
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.v1.resources import Actor, Db, context, require
from app.auth.dependencies import require_csrf
from app.core.config import get_settings
from app.documents.upload import UploadService
from app.storage.seaweed import create_storage

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", status_code=202, dependencies=[Depends(require_csrf)])
async def upload_document(
    request: Request,
    db: Db,
    user: Actor,
    parent_id: uuid.UUID,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> dict[str, object]:
    await require(db, user, "CREATE", parent_id)
    settings = get_settings()
    size = 0
    with tempfile.TemporaryFile() as source:
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.upload_max_bytes:
                raise HTTPException(413, "Upload exceeds configured limit")
            await run_in_threadpool(source.write, chunk)
        version = await UploadService(db, create_storage(settings)).create(
            user, parent_id, filename, source, context(request)
        )
    return {
        "data": {
            "document_id": version.document_id,
            "version_id": version.id,
            "status": version.status,
            "sha256": version.sha256,
        }
    }
