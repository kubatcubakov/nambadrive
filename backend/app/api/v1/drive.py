import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from app.api.v1.resources import Actor, Db, context, require
from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.drive.service import DriveService
from app.models.access_review import AccessReview
from app.models.document import DocumentVersion
from app.models.lifecycle import OwnershipTransfer
from app.models.notification import NotificationDelivery
from app.models.quota import StorageReservation
from app.models.resource import Resource
from app.models.user import User

router = APIRouter(tags=["drive"])


@router.get("/drive")
async def listing(
    request: Request,
    response: Response,
    db: Db,
    actor: Actor,
    view: Literal[
        "mine", "shared", "spaces", "departments", "recent", "favorites", "trash"
    ] = "mine",
    department_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1, le=1000),
):
    response.headers["Cache-Control"] = "no-store"
    return {
        "data": await DriveService(db, actor, context(request)).listing(view, department_id, page)
    }


@router.get("/drive/capabilities")
async def capabilities(db: Db, actor: Actor):
    authorization = AuthorizationService()
    return {
        "data": {
            "administration": (
                await authorization.authorize(db, actor, "RECEIVE_ADMIN_ALERTS", None)
            ).allowed,
            "organization": await authorization.organization_admin(db, actor),
        }
    }


@router.put("/favorites/{resource_id}", dependencies=[Depends(require_csrf)])
async def favorite(resource_id: uuid.UUID, request: Request, db: Db, actor: Actor):
    await DriveService(db, actor, context(request)).favorite(resource_id, True)
    return {"data": {"favorite": True}}


@router.delete("/favorites/{resource_id}", dependencies=[Depends(require_csrf)])
async def unfavorite(resource_id: uuid.UUID, request: Request, db: Db, actor: Actor):
    await DriveService(db, actor, context(request)).favorite(resource_id, False)
    return {"data": {"favorite": False}}


@router.get("/admin/dashboard")
async def dashboard(db: Db, actor: Actor, response: Response):
    await require(db, actor, "RECEIVE_ADMIN_ALERTS", None)
    response.headers["Cache-Control"] = "no-store"
    counts = {}
    for key, model, condition in [
        ("enabled_users", User, User.enabled.is_(True)),
        ("disabled_users", User, User.enabled.is_(False)),
        (
            "active_documents",
            Resource,
            (Resource.resource_type == "DOCUMENT")
            & (Resource.state == "ACTIVE")
            & Resource.purged_at.is_(None),
        ),
        (
            "quarantined_versions",
            DocumentVersion,
            (DocumentVersion.status == "PENDING") & DocumentVersion.purged_at.is_(None),
        ),
        (
            "infected_versions",
            DocumentVersion,
            (DocumentVersion.status == "INFECTED") & DocumentVersion.purged_at.is_(None),
        ),
        ("pending_deliveries", NotificationDelivery, NotificationDelivery.status == "PENDING"),
        ("pending_transfers", OwnershipTransfer, None),
        ("open_access_reviews", AccessReview, AccessReview.completed_at.is_(None)),
    ]:
        query = select(func.count()).select_from(model)
        if condition is not None:
            query = query.where(condition)
        counts[key] = await db.scalar(query)
    sizes = await db.scalar(
        select(func.coalesce(func.sum(DocumentVersion.size), 0)).where(
            DocumentVersion.purged_at.is_(None)
        )
    )
    reservations = await db.scalar(
        select(func.coalesce(func.sum(StorageReservation.size), 0)).where(
            ~select(DocumentVersion.id)
            .where(DocumentVersion.id == StorageReservation.version_id)
            .exists()
        )
    )
    counts["logical_bytes"] = (sizes or 0) + (reservations or 0)
    return {"data": counts}
