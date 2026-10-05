import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select

from app.api.v1.resources import Actor, Db, context
from app.auth.dependencies import require_csrf
from app.governance.service import GovernanceService
from app.models.governance import LegalHoldEvent, RetentionPolicy
from app.models.resource import Resource

router = APIRouter(prefix="/admin/governance", tags=["governance"])


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class PolicyInput(ReasonInput):
    name: str = Field(min_length=1, max_length=200)
    resource_id: uuid.UUID | None = None
    document_type: str | None = Field(default=None, max_length=10)
    days: int = Field(ge=1, le=36500)


class HoldInput(ReasonInput):
    enabled: bool


class RetentionInput(ReasonInput):
    until: AwareDatetime


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@router.get("/policies")
async def policies(request: Request, response: Response, db: Db, user: Actor):
    await GovernanceService(db, user, context(request)).require("MANAGE_RETENTION")
    response.headers["Cache-Control"] = "no-store"
    return {
        "data": [
            record(row)
            for row in (
                await db.scalars(
                    select(RetentionPolicy).order_by(RetentionPolicy.created_at.desc())
                )
            ).all()
        ]
    }


@router.post("/policies", status_code=201, dependencies=[Depends(require_csrf)])
async def create_policy(payload: PolicyInput, request: Request, db: Db, user: Actor):
    row = await GovernanceService(db, user, context(request)).create_policy(**payload.model_dump())
    return {"data": record(row)}


@router.post("/policies/{policy_id}/revoke", dependencies=[Depends(require_csrf)])
async def revoke_policy(
    policy_id: uuid.UUID, payload: ReasonInput, request: Request, db: Db, user: Actor
):
    await GovernanceService(db, user, context(request)).revoke_policy(policy_id, payload.reason)
    return {"data": {"revoked": True}}


@router.get("/resources/{resource_id}")
async def resource_policy(
    resource_id: uuid.UUID, request: Request, response: Response, db: Db, user: Actor
):
    service = GovernanceService(db, user, context(request))
    await service.require("MANAGE_LEGAL_HOLD")
    row = await db.get(Resource, resource_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(404, "Policy scope unavailable")
    history = (
        await db.scalars(
            select(LegalHoldEvent)
            .where(LegalHoldEvent.resource_id == resource_id)
            .order_by(LegalHoldEvent.created_at)
        )
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "data": {
            "resource_id": row.id,
            "legal_hold": row.legal_hold,
            "retention_until": row.retention_until,
            "purged_at": row.purged_at,
            "hold_history": [record(event) for event in history],
        }
    }


@router.put("/resources/{resource_id}/hold", dependencies=[Depends(require_csrf)])
async def set_hold(
    resource_id: uuid.UUID, payload: HoldInput, request: Request, db: Db, user: Actor
):
    row = await GovernanceService(db, user, context(request)).hold(
        resource_id, payload.enabled, payload.reason
    )
    return {"data": {"resource_id": row.id, "legal_hold": row.legal_hold}}


@router.put("/resources/{resource_id}/retention", dependencies=[Depends(require_csrf)])
async def extend_retention(
    resource_id: uuid.UUID, payload: RetentionInput, request: Request, db: Db, user: Actor
):
    row = await GovernanceService(db, user, context(request)).extend(
        resource_id, payload.until, payload.reason
    )
    return {"data": {"resource_id": row.id, "retention_until": row.retention_until}}


@router.get("/capabilities")
async def capabilities(db: Db, user: Actor):
    from app.authorization.service import AuthorizationService

    return {
        "data": {
            permission: (await AuthorizationService().authorize(db, user, permission, None)).allowed
            for permission in ["MANAGE_RETENTION", "MANAGE_LEGAL_HOLD"]
        }
    }
