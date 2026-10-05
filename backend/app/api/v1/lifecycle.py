import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.resources import Actor, Db, require
from app.auth.dependencies import require_csrf
from app.lifecycle.service import LifecycleService
from app.models.lifecycle import IdentityPolicy, OwnershipTransfer
from app.users.service import User

router = APIRouter(prefix="/identity", tags=["identity"])


class PolicyInput(BaseModel):
    global_owner_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)


@router.get("")
async def status(db: Db, actor: Actor, response: Response):
    await require(db, actor, "MANAGE_IDENTITY", None)
    response.headers["Cache-Control"] = "no-store"
    policy = await db.get(IdentityPolicy, "GLOBAL")
    tasks = (await db.scalars(select(OwnershipTransfer))).all()
    users = (await db.scalars(select(User).order_by(User.display_name))).all()
    return {
        "data": {
            "global_owner_id": policy.global_owner_id if policy else None,
            "pending_transfers": [
                {"resource_id": t.resource_id, "previous_owner_id": t.previous_owner_id}
                for t in tasks
            ],
            "users": [
                {"id": u.id, "display_name": u.display_name, "enabled": u.enabled} for u in users
            ],
        }
    }


@router.put("/policy", dependencies=[Depends(require_csrf)])
async def configure(payload: PolicyInput, request: Request, db: Db, actor: Actor):
    await LifecycleService(db, str(actor.id)).configure(
        actor, payload.global_owner_id, payload.reason
    )
    return {"data": {"configured": True}}


@router.post("/{user_id}/disable", dependencies=[Depends(require_csrf)])
async def disable(user_id: uuid.UUID, db: Db, actor: Actor):
    from app.governance.policy import governance_lock

    await governance_lock(db)
    await require(db, actor, "MANAGE_IDENTITY", None)
    user = await db.get(User, user_id, populate_existing=True, with_for_update=True)
    if user is None:
        raise HTTPException(404, "User not found")
    await LifecycleService(db, str(actor.id)).disable(user)
    await db.commit()
    return {"data": {"enabled": False}}
