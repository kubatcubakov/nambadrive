from __future__ import annotations

import tempfile
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.v1.resources import Actor, Db, context, require
from app.auth.dependencies import require_csrf
from app.auth.sessions import get_session_user
from app.core.config import get_settings
from app.documents.service import read_verified
from app.models.document import DocumentVersion
from app.office.security import verify_outbox
from app.office.service import OfficeService
from app.storage.seaweed import create_storage

router = APIRouter(prefix="/office", tags=["office"])


@router.post("/{document_id}/session", dependencies=[Depends(require_csrf)])
async def editor_session(
    document_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    await require(db, user, "EDIT", document_id)
    settings = get_settings()
    login = await get_session_user(db, request.cookies.get(settings.session_cookie_name, ""))
    if login is None or login[1].id != user.id:
        raise HTTPException(401, "Application session unavailable")
    return {
        "data": await OfficeService(db, settings, context(request)).open(
            user, document_id, login[0]
        )
    }


def signed_payload(authorization: str | None) -> dict[str, object]:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(403, "Office server signature required")
    return verify_outbox(authorization[7:], get_settings())


@router.get("/internal/content/{session_id}")
async def office_content(
    session_id: uuid.UUID,
    request: Request,
    db: Db,
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    payload = signed_payload(authorization)
    settings = get_settings()
    expected = (
        settings.office_backend_url.rstrip("/") + f"/api/v1/office/internal/content/{session_id}"
    )
    if payload != {"url": expected}:
        raise HTTPException(403, "Office content signature mismatch")
    service = OfficeService(db, settings, context(request))
    _, room, _ = await service.session(session_id)
    version = await db.get(DocumentVersion, room.base_version_id)
    if version is None or version.status != "CLEAN" or version.document_id != room.document_id:
        raise HTTPException(403, "Office base version unavailable")
    source = tempfile.TemporaryFile()
    try:
        await run_in_threadpool(read_verified, create_storage(settings), version, source)
        await service.session(session_id)
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
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/internal/callback/{session_id}")
async def office_callback(
    session_id: uuid.UUID,
    request: Request,
    db: Db,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    payload = signed_payload(authorization)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise HTTPException(413, "Callback too large")
    import json

    try:
        posted = json.loads(body)
    except ValueError:
        raise HTTPException(422, "Invalid callback body") from None
    if posted != payload:
        raise HTTPException(403, "Unsigned callback parameters")
    settings = get_settings()
    return await OfficeService(db, settings, context(request)).callback(
        session_id, payload, create_storage(settings)
    )


class NewOfficeDocument(BaseModel):
    parent_id: uuid.UUID
    name: str = Field(min_length=1, max_length=240)
    format: Literal["docx", "xlsx", "pptx"]


@router.post("/create", status_code=202, dependencies=[Depends(require_csrf)])
async def create_office_document(
    payload: NewOfficeDocument, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.documents.upload import UploadService
    from app.office.templates import blank

    await require(db, user, "CREATE", payload.parent_id)
    settings = get_settings()
    content = await run_in_threadpool(blank, payload.format)
    try:
        version = await UploadService(db, create_storage(settings)).create(
            user, payload.parent_id, payload.name + "." + payload.format, content, context(request)
        )
    finally:
        content.close()
    return {
        "data": {
            "document_id": version.document_id,
            "version_id": version.id,
            "status": version.status,
        }
    }
