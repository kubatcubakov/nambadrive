import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api.v1.resources import Actor, Db
from app.auth.dependencies import require_csrf
from app.models.notification import NotificationPreference
from app.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class Preferences(BaseModel):
    email_enabled: bool


@router.get("")
async def list_notifications(response: Response, db: Db, user: Actor):
    response.headers["Cache-Control"] = "no-store"
    return {"data": await NotificationService(db).list(user)}


@router.post("/{notification_id}/read", dependencies=[Depends(require_csrf)])
async def read_notification(notification_id: uuid.UUID, db: Db, user: Actor):
    await NotificationService(db).read(user, notification_id)
    return {"data": {"read": True}}


@router.get("/preferences")
async def preferences(response: Response, db: Db, user: Actor):
    await NotificationService(db).own(user)
    response.headers["Cache-Control"] = "no-store"
    row = await db.get(NotificationPreference, user.id)
    return {"data": {"email_enabled": row.email_enabled if row else True}}


@router.put("/preferences", dependencies=[Depends(require_csrf)])
async def set_preferences(payload: Preferences, db: Db, user: Actor):
    await NotificationService(db).own(user)
    row = await db.get(NotificationPreference, user.id)
    if row is None:
        row = NotificationPreference(user_id=user.id)
        db.add(row)
    row.email_enabled = payload.email_enabled
    await db.commit()
    return {"data": {"email_enabled": row.email_enabled}}
