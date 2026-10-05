import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access_reviews.service import ReviewService
from app.api.v1.resources import Actor, Db, context
from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.models.access_review import AccessReviewItem

router = APIRouter(prefix="/access-reviews", tags=["access-reviews"])


class DecisionInput(BaseModel):
    decision: Literal["KEEP", "REVOKE"]
    reason: str = Field(min_length=1, max_length=2000)


@router.get("")
async def list_reviews(request: Request, response: Response, db: Db, user: Actor):
    response.headers["Cache-Control"] = "no-store"
    return {"data": await ReviewService(db, user, context(request)).list()}


@router.get("/{review_id}")
async def review_details(
    review_id: uuid.UUID, request: Request, response: Response, db: Db, user: Actor
):
    review = await ReviewService(db, user, context(request)).get(review_id)
    response.headers["Cache-Control"] = "no-store"
    items = (
        await db.scalars(
            select(AccessReviewItem)
            .where(AccessReviewItem.review_id == review.id)
            .order_by(AccessReviewItem.source_key, AccessReviewItem.id)
        )
    ).all()
    result = []
    for item in items:
        origin = item.snapshot.get("origin")
        can_revoke = (
            origin is not None
            and item.snapshot["kind"] in {"ACL", "ROLE"}
            and (
                await AuthorizationService().authorize(db, user, "CHANGE_ACL", uuid.UUID(origin))
            ).allowed
        )
        result.append(
            dict(
                id=item.id,
                snapshot=item.snapshot,
                decision=item.decision,
                reason=item.reason,
                decided_by=item.decided_by,
                decided_at=item.decided_at,
                can_revoke=can_revoke,
            )
        )
    return {
        "data": dict(
            id=review.id,
            resource_id=review.resource_id,
            quarter=review.quarter,
            due_at=review.due_at,
            completed_at=review.completed_at,
            items=result,
        )
    }


@router.post("/{review_id}/refresh", dependencies=[Depends(require_csrf)])
async def refresh_review(review_id: uuid.UUID, request: Request, db: Db, user: Actor):
    await ReviewService(db, user, context(request)).refresh(review_id)
    return {"data": {"refreshed": True}}


@router.post("/{review_id}/items/{item_id}", dependencies=[Depends(require_csrf)])
async def decide_item(
    review_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: DecisionInput,
    request: Request,
    db: Db,
    user: Actor,
):
    await ReviewService(db, user, context(request)).decide(
        review_id, item_id, payload.decision, payload.reason
    )
    return {"data": {"decided": True}}


@router.post("/{review_id}/complete", dependencies=[Depends(require_csrf)])
async def complete_review(review_id: uuid.UUID, request: Request, db: Db, user: Actor):
    await ReviewService(db, user, context(request)).complete(review_id)
    return {"data": {"completed": True}}
