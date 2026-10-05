import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, Field

from app.access_requests.service import AccessRequestService
from app.api.v1.resources import Actor, Db, context
from app.auth.dependencies import require_csrf

router = APIRouter(prefix="/access-requests", tags=["access-requests"])


class RequestInput(BaseModel):
    resource_id: uuid.UUID
    permission: Literal["VIEW", "EDIT", "DOWNLOAD"]
    reason: str = Field(min_length=1, max_length=2000)
    valid_until: AwareDatetime | None = None


class DecisionInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    valid_until: AwareDatetime | None = None


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
async def create_request(payload: RequestInput, request: Request, db: Db, user: Actor):
    service = AccessRequestService(db, user, context(request))
    row = await service.create(
        payload.resource_id, payload.permission, payload.reason, payload.valid_until
    )
    return {"data": service.record(row)}


@router.get("/mine")
async def mine(request: Request, response: Response, db: Db, user: Actor):
    response.headers["Cache-Control"] = "no-store"
    return {"data": await AccessRequestService(db, user, context(request)).list_requests(False)}


@router.get("/inbox")
async def inbox(request: Request, response: Response, db: Db, user: Actor):
    response.headers["Cache-Control"] = "no-store"
    return {"data": await AccessRequestService(db, user, context(request)).list_requests(True)}


@router.get("/discovery")
async def discovery(
    request: Request,
    response: Response,
    db: Db,
    user: Actor,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    response.headers["Cache-Control"] = "no-store"
    return {"data": await AccessRequestService(db, user, context(request)).discover(q, limit)}


@router.post("/{request_id}/{action}", dependencies=[Depends(require_csrf)])
async def decide(
    request_id: uuid.UUID,
    action: Literal["approve", "deny"],
    payload: DecisionInput,
    request: Request,
    db: Db,
    user: Actor,
):
    service = AccessRequestService(db, user, context(request))
    row = await service.decide(request_id, action == "approve", payload.reason, payload.valid_until)
    return {"data": service.record(row)}
