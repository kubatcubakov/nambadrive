from __future__ import annotations

import tempfile
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
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


@router.get("/trash")
async def trash_documents(db: Db, user: Actor) -> dict[str, object]:
    from sqlalchemy import select

    from app.api.v1.resources import serialize
    from app.authorization.service import AuthorizationService
    from app.models.resource import Resource

    rows = (
        await db.scalars(
            select(Resource).where(Resource.resource_type == "DOCUMENT", Resource.state == "TRASH")
        )
    ).all()
    visible = []
    for row in rows:
        if (await AuthorizationService().authorize(db, user, "RESTORE", row.id)).allowed:
            visible.append(serialize(row))
    return {"data": visible}


@router.get("/{document_id}")
async def document_metadata(
    document_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.api.v1.resources import serialize
    from app.documents.service import DocumentService
    from app.models.metadata import DocumentMetadata

    service = DocumentService(db, user, context(request))
    row = await service.require(document_id, "VIEW")
    version = await service.current(document_id)
    metadata = await db.get(DocumentMetadata, document_id)
    await service.audit("view", row)
    return {
        "data": {
            **serialize(row),
            "version_id": version.id,
            "size": version.size,
            "sha256": version.sha256,
            "mime_type": version.mime_type,
            "metadata": {c.name: getattr(metadata, c.name) for c in metadata.__table__.columns}
            if metadata
            else {},
        }
    }


class MetadataInput(BaseModel):
    project_id: uuid.UUID | None = None
    counterparty: str | None = Field(default=None, max_length=255)
    contract_number: str | None = Field(default=None, max_length=255)
    contract_date: date | None = None
    contract_expiry: date | None = None
    tags: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=10000)


class RenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DestinationInput(BaseModel):
    parent_id: uuid.UUID


@router.put("/{document_id}/metadata", dependencies=[Depends(require_csrf)])
async def update_metadata(
    document_id: uuid.UUID, payload: MetadataInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService
    from app.models.metadata import DocumentMetadata

    service = DocumentService(db, user, context(request))
    row = await service.require(document_id, "EDIT")
    metadata = await db.get(DocumentMetadata, document_id)
    if metadata is None:
        metadata = DocumentMetadata(document_id=document_id)
        db.add(metadata)
    for key, value in payload.model_dump().items():
        setattr(metadata, key, value)
    await service.audit("edit", row, operation="metadata")
    await db.commit()
    return {"data": payload.model_dump()}


@router.post("/{document_id}/rename", dependencies=[Depends(require_csrf)])
async def rename_document(
    document_id: uuid.UUID, payload: RenameInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService

    row = await DocumentService(db, user, context(request)).rename(document_id, payload.name)
    return {"data": {"id": row.id, "name": row.name}}


@router.post("/{document_id}/move", dependencies=[Depends(require_csrf)])
async def move_document(
    document_id: uuid.UUID, payload: DestinationInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService

    row = await DocumentService(db, user, context(request)).move(document_id, payload.parent_id)
    return {"data": {"id": row.id, "parent_id": row.parent_id}}


@router.post("/{document_id}/copy", dependencies=[Depends(require_csrf)])
async def copy_document(
    document_id: uuid.UUID, payload: DestinationInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService

    service = DocumentService(db, user, context(request))
    await service.require(document_id, "COPY")
    row = await service.copy(document_id, payload.parent_id, create_storage(get_settings()))
    return {"data": {"id": row.id}}


@router.delete("/{document_id}", dependencies=[Depends(require_csrf)])
async def trash_document(
    document_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService

    await DocumentService(db, user, context(request)).trash(document_id)
    return {"data": {"deleted": True}}


@router.post("/{document_id}/restore", dependencies=[Depends(require_csrf)])
async def restore_document(
    document_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.service import DocumentService

    row = await DocumentService(db, user, context(request)).restore(document_id)
    return {"data": {"id": row.id}}


@router.get("/{document_id}/download")
async def download_document(document_id: uuid.UUID, request: Request, db: Db, user: Actor):
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    from app.documents.service import DocumentService, read_verified

    service = DocumentService(db, user, context(request))
    row = await service.require(document_id, "DOWNLOAD")
    version = await service.current(document_id)
    source = tempfile.TemporaryFile()
    try:
        await run_in_threadpool(read_verified, create_storage(get_settings()), version, source)
        await service.require(document_id, "DOWNLOAD")
        await service.audit("download", row)
    except BaseException:
        source.close()
        raise

    def chunks():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.name, safe=""),
            "Content-Length": str(version.size),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/{document_id}/preview")
async def preview_document(
    document_id: uuid.UUID,
    request: Request,
    db: Db,
    user: Actor,
    page: int = Query(default=0, ge=0, le=10000),
):
    import subprocess  # nosec B404
    import sys

    from fastapi.responses import Response

    from app.documents.service import DocumentService, read_verified

    service = DocumentService(db, user, context(request))
    row = await service.require(document_id, "PREVIEW")
    version = await service.current(document_id)
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
        await run_in_threadpool(read_verified, create_storage(get_settings()), version, source.file)
        source.flush()

        def render():
            try:
                process = subprocess.run(
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
                )  # nosec B603
                return process.stdout
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                raise HTTPException(422, "Preview could not be generated") from None

        content = await run_in_threadpool(render)
    await service.require(document_id, "PREVIEW")
    await service.audit("preview", row)
    return Response(
        content,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/{document_id}/versions")
async def version_history(
    document_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.versions import VersionService

    rows = await VersionService(db, user, context(request)).history(document_id)
    return {
        "data": [
            {
                "id": row.id,
                "number": row.sequence_no,
                "size": row.size,
                "sha256": row.sha256,
                "created_at": row.created_at,
                "is_current": row.is_current,
                "uploaded_by": row.uploaded_by,
            }
            for row in rows
        ]
    }


@router.post("/{document_id}/versions", status_code=202, dependencies=[Depends(require_csrf)])
async def upload_version(
    document_id: uuid.UUID,
    request: Request,
    db: Db,
    user: Actor,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> dict[str, object]:
    await require(db, user, "UPLOAD_NEW_VERSION", document_id)
    settings = get_settings()
    size = 0
    with tempfile.TemporaryFile() as source:
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.upload_max_bytes:
                raise HTTPException(413, "Upload exceeds configured limit")
            await run_in_threadpool(source.write, chunk)
        version = await UploadService(db, create_storage(settings)).new_version(
            user, document_id, filename, source, context(request)
        )
    return {
        "data": {"version_id": version.id, "number": version.sequence_no, "status": version.status}
    }


@router.post("/{document_id}/versions/{version_id}/restore", dependencies=[Depends(require_csrf)])
async def restore_version(
    document_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.versions import VersionService

    await require(db, user, "RESTORE_VERSION", document_id)
    version = await VersionService(db, user, context(request)).restore(
        document_id, version_id, create_storage(get_settings())
    )
    return {"data": {"version_id": version.id, "number": version.sequence_no}}
