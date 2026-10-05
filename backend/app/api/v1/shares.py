from __future__ import annotations

import tempfile
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from app.api.v1.resources import Actor, Db, context
from app.auth.dependencies import require_csrf
from app.core.config import get_settings
from app.documents.rendering import raster_preview
from app.documents.service import DocumentService, read_verified
from app.models.share import ExternalShare
from app.shares.security import limit_attempts, token_hash
from app.shares.service import ShareService
from app.storage.seaweed import create_storage

router = APIRouter(prefix="/shares", tags=["shares"])


def record(share: ExternalShare) -> dict[str, object]:
    return {
        "id": share.id,
        "created_by": share.created_by,
        "created_at": share.created_at,
        "expires_at": share.expires_at,
        "revoked_at": share.revoked_at,
        "max_views": share.max_views,
        "views": share.views,
        "allow_view": share.allow_view,
        "allow_download": share.allow_download,
        "password_protected": share.password_hash is not None,
    }


class ShareInput(BaseModel):
    days: int = Field(default=7, ge=1, le=30)
    password: SecretStr | None = Field(default=None, min_length=12, max_length=128)
    max_views: int | None = Field(default=None, ge=1, le=1000000)
    allow_view: bool = True
    allow_download: bool = False


@router.post("/internal/{document_id}", dependencies=[Depends(require_csrf)])
async def internal_link(document_id: uuid.UUID, request: Request, db: Db, user: Actor):
    service = DocumentService(db, user, context(request))
    row = await service.require(document_id, "SHARE")
    await service.require(document_id, "VIEW")
    await service.audit("share", row, operation="internal_link")
    return {"data": {"path": "/?document=" + str(document_id)}}


@router.get("/documents/{document_id}")
async def list_shares(
    document_id: uuid.UUID, request: Request, response: Response, db: Db, user: Actor
):
    response.headers["Cache-Control"] = "no-store"
    rows = await ShareService(db, context(request)).list(user, document_id)
    return {"data": [record(row) for row in rows]}


@router.post("/documents/{document_id}", status_code=201, dependencies=[Depends(require_csrf)])
async def create_share(
    document_id: uuid.UUID,
    payload: ShareInput,
    request: Request,
    response: Response,
    db: Db,
    user: Actor,
):
    share, token = await ShareService(db, context(request)).create(
        user,
        document_id,
        days=payload.days,
        password=payload.password.get_secret_value() if payload.password else None,
        max_views=payload.max_views,
        allow_view=payload.allow_view,
        allow_download=payload.allow_download,
    )
    response.headers["Cache-Control"] = "no-store"
    # Fragment is not transmitted in URLs to the server, proxies or Referer headers.
    return {"data": {**record(share), "path": "/share#" + token}}


@router.delete("/documents/{document_id}/{share_id}", dependencies=[Depends(require_csrf)])
async def revoke_share(
    document_id: uuid.UUID, share_id: uuid.UUID, request: Request, db: Db, user: Actor
):
    await ShareService(db, context(request)).revoke(user, document_id, share_id)
    return {"data": {"revoked": True}}


class AccessInput(BaseModel):
    token: SecretStr = Field(min_length=43, max_length=43)
    password: SecretStr | None = Field(default=None, max_length=128)
    action: Literal["preview", "download"] = "preview"
    page: int = Field(default=0, ge=0, le=10000)


@router.post("/access")
async def access_share(payload: AccessInput, request: Request, db: Db):
    token = payload.token.get_secret_value()
    await limit_attempts(request.client.host if request.client else "unknown", token_hash(token))
    permission = "DOWNLOAD" if payload.action == "download" else "PREVIEW"
    service = ShareService(db, context(request))
    share, creator = await service.resolve(
        token, payload.password.get_secret_value() if payload.password else None, permission
    )
    documents = DocumentService(db, creator, context(request))
    row = await documents.require(share.document_id, permission)
    version = await documents.current(row.id)
    storage = create_storage(get_settings())
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Referrer-Policy": "no-referrer",
    }
    if permission == "PREVIEW":
        content = await raster_preview(storage, version, payload.page)
        await service.consume(share, permission)
        return Response(content, media_type="image/png", headers=headers)
    source = tempfile.TemporaryFile()
    try:
        await run_in_threadpool(read_verified, storage, version, source)
        await service.consume(share, permission)
    except BaseException:
        source.close()
        raise

    def chunks():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(row.name, safe="")
    headers["Content-Length"] = str(version.size)
    return StreamingResponse(chunks(), media_type="application/octet-stream", headers=headers)
