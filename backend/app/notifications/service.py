from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.authorization.service import AuthorizationService
from app.models.access_request import AccessRequest
from app.models.acl import BreakGlassGrant
from app.models.document import DocumentVersion
from app.models.notification import Notification, NotificationDelivery, NotificationSource
from app.models.quota import QuotaIncident
from app.models.resource import Resource
from app.models.user import User

MESSAGES = {
    "QUOTA": "Превышена квота хранилища. Новая запись отклонена.",
    "ACCESS_PENDING": "Новый запрос доступа ожидает решения владельца или менеджера.",
    "ACCESS_DECIDED": "По вашему запросу доступа принято решение. Откройте раздел запросов.",
    "MALWARE": "Обнаружен вредоносный файл. Он остаётся в карантине.",
    "BREAK_GLASS": "Активирован аварийный доступ. Проверьте журнал аудита.",
}


async def permitted(db: AsyncSession, user: User, notice: Notification) -> bool:
    authorization = AuthorizationService()
    if not await authorization.account_self(db, user, notice.user_id):
        return False
    return (
        not notice.admin_only
        or (await authorization.authorize(db, user, "RECEIVE_ADMIN_ALERTS", None)).allowed
    )


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.authorization = AuthorizationService()

    async def own(self, actor: User) -> None:
        if not await self.authorization.account_self(self.db, actor, actor.id):
            raise HTTPException(403, "Notifications unavailable")

    async def list(self, actor: User) -> list[dict]:
        await self.own(actor)
        rows = (
            await self.db.scalars(
                select(Notification)
                .where(Notification.user_id == actor.id)
                .order_by(Notification.created_at.desc(), Notification.id)
                .limit(100)
            )
        ).all()
        result = []
        for row in rows:
            if not await permitted(self.db, actor, row):
                continue
            visible = (
                row.resource_id is not None
                and (
                    await self.authorization.authorize(self.db, actor, "VIEW", row.resource_id)
                ).allowed
            )
            result.append(
                dict(
                    id=row.id,
                    kind=row.kind,
                    message=MESSAGES[row.kind],
                    created_at=row.created_at,
                    read_at=row.read_at,
                    resource_id=row.resource_id if visible else None,
                )
            )
        return result

    async def read(self, actor: User, notice_id: uuid.UUID) -> None:
        row = await self.db.get(Notification, notice_id, with_for_update=True)
        if row is None or not await permitted(self.db, actor, row):
            raise HTTPException(403, "Notifications unavailable")
        row.read_at = row.read_at or datetime.now(UTC)
        await self.db.commit()

    async def collect(self) -> int:
        # Independent producer lock; receipts and fanout commit atomically.
        if self.db.get_bind().dialect.name == "postgresql":
            await self.db.execute(text("SELECT pg_advisory_xact_lock(735915)"))
        users = (await self.db.scalars(select(User).where(User.enabled.is_(True)))).all()
        admins = [
            u
            for u in users
            if (
                await self.authorization.authorize(self.db, u, "RECEIVE_ADMIN_ALERTS", None)
            ).allowed
        ]
        count = 0
        sources: list[
            tuple[
                str,
                type[QuotaIncident]
                | type[AccessRequest]
                | type[DocumentVersion]
                | type[BreakGlassGrant],
                ColumnElement[bool] | None,
            ]
        ] = [
            ("QUOTA", QuotaIncident, None),
            ("ACCESS_PENDING", AccessRequest, None),
            ("ACCESS_DECIDED", AccessRequest, AccessRequest.status != "PENDING"),
            ("MALWARE", DocumentVersion, DocumentVersion.status == "INFECTED"),
            ("BREAK_GLASS", BreakGlassGrant, BreakGlassGrant.audited.is_(True)),
        ]
        for kind, model, condition in sources:
            query = (
                select(model)
                .where(
                    ~select(NotificationSource.source_id)
                    .where(
                        NotificationSource.kind == kind, NotificationSource.source_id == model.id
                    )
                    .exists()
                )
                .order_by(model.id)
                .limit(100)
            )
            if condition is not None:
                query = query.where(condition)
            for source in (await self.db.scalars(query)).all():
                if not isinstance(
                    source, (QuotaIncident, AccessRequest, DocumentVersion, BreakGlassGrant)
                ):
                    raise TypeError("Invalid notification source")
                recipients: dict[uuid.UUID, bool] = {}
                resource_id = getattr(source, "resource_id", None)
                if kind in {"QUOTA", "MALWARE", "BREAK_GLASS"}:
                    recipients.update({u.id: True for u in admins})
                if isinstance(source, QuotaIncident):
                    recipients[source.actor_id] = False
                    source.notified_at = datetime.now(UTC)
                elif isinstance(source, DocumentVersion):
                    resource_id = source.document_id
                    recipients[source.uploaded_by] = False
                elif isinstance(source, AccessRequest):
                    if kind == "ACCESS_DECIDED":
                        recipients[source.requested_by] = False
                    elif source.status == "PENDING":
                        for user in users:
                            if (
                                await self.authorization.authorize_request_approval(
                                    self.db, user, source.resource_id
                                )
                            ).allowed:
                                recipients[user.id] = False
                # Failed new-document writes may reference a rolled-back resource UUID.
                if resource_id and await self.db.get(Resource, resource_id) is None:
                    resource_id = None
                for user in users:
                    if user.id not in recipients:
                        continue
                    row = Notification(
                        kind=kind,
                        source_id=source.id,
                        user_id=user.id,
                        resource_id=resource_id,
                        admin_only=recipients[user.id],
                    )
                    self.db.add(row)
                    await self.db.flush()
                    self.db.add(NotificationDelivery(notification_id=row.id, channel="EMAIL"))
                    # One generic Telegram alert per source, never ordinary user events.
                    if (
                        admins
                        and user.id == admins[0].id
                        and kind in {"QUOTA", "MALWARE", "BREAK_GLASS"}
                    ):
                        self.db.add(
                            NotificationDelivery(notification_id=row.id, channel="TELEGRAM")
                        )
                self.db.add(NotificationSource(kind=kind, source_id=source.id))
                count += 1
        await self.db.commit()
        return count
