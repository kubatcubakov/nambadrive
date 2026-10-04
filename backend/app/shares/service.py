from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.writer import write_audit_event
from app.authorization.service import AuthorizationService
from app.documents.service import DocumentService
from app.models.resource import Resource
from app.models.share import ExternalShare
from app.models.user import User
from app.shares.security import password_hash, token_hash, verify_password


class ShareService:
    def __init__(self, db: AsyncSession, context: dict[str, Any]) -> None:
        self.db, self.context = db, context

    async def create(
        self,
        actor: User,
        document_id: uuid.UUID,
        *,
        days: int = 7,
        password: str | None = None,
        max_views: int | None = None,
        allow_view: bool = True,
        allow_download: bool = False,
    ) -> tuple[ExternalShare, str]:
        if not 1 <= days <= 30 or (max_views is not None and max_views < 1):
            raise ValueError("Invalid share limits")
        if not (allow_view or allow_download) or (
            password is not None and not 12 <= len(password) <= 128
        ):
            raise ValueError("Invalid share options")
        service = DocumentService(self.db, actor, self.context)
        for permission in (
            ["SHARE", "EXTERNAL_SHARE", "VIEW"]
            + (["PREVIEW"] if allow_view else [])
            + (["DOWNLOAD"] if allow_download else [])
        ):
            await service.require(document_id, permission)
        await service.current(document_id)
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        share = ExternalShare(
            document_id=document_id,
            created_by=actor.id,
            token_hash=token_hash(token),
            password_hash=await run_in_threadpool(password_hash, password) if password else None,
            allow_view=allow_view,
            allow_download=allow_download,
            max_views=max_views,
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
        self.db.add(share)
        await self.db.flush()
        await write_audit_event(
            "share",
            user=str(actor.id),
            resource=str(document_id),
            result="success",
            operation="create_external",
            share_id=str(share.id),
            expires_at=share.expires_at.isoformat(),
            max_views=max_views,
            allow_view=allow_view,
            allow_download=allow_download,
            password_protected=bool(password),
            **self.context,
        )
        await self.db.commit()
        return share, token

    async def list(self, actor: User, document_id: uuid.UUID) -> list[ExternalShare]:
        await DocumentService(self.db, actor, self.context).require(document_id, "SHARE")
        return list(
            (
                await self.db.scalars(
                    select(ExternalShare)
                    .where(ExternalShare.document_id == document_id)
                    .order_by(ExternalShare.created_at.desc())
                )
            ).all()
        )

    async def revoke(self, actor: User, document_id: uuid.UUID, share_id: uuid.UUID) -> None:
        # Ordinary SHARE is sufficient to revoke even after classification becomes non-public.
        await DocumentService(self.db, actor, self.context).require(document_id, "SHARE")
        share = await self.db.get(ExternalShare, share_id, with_for_update=True)
        if share is None or share.document_id != document_id:
            raise HTTPException(404, "Share unavailable")
        share.revoked_at = datetime.now(UTC)
        await write_audit_event(
            "share",
            user=str(actor.id),
            resource=str(document_id),
            result="success",
            operation="revoke_external",
            share_id=str(share.id),
            **self.context,
        )
        await self.db.commit()

    async def resolve(
        self, token: str, password: str | None, permission: str
    ) -> tuple[ExternalShare, User]:
        # Discover ID first, then use the same document -> share lock ordering as management.
        share = await self.db.scalar(
            select(ExternalShare).where(ExternalShare.token_hash == token_hash(token))
        )
        if share is None:
            raise HTTPException(403, "Share unavailable")
        await self.db.get(Resource, share.document_id, with_for_update=True)
        await self.db.refresh(share, with_for_update=True)
        password_valid = share.password_hash is None or await run_in_threadpool(
            verify_password, password or "", share.password_hash
        )
        decision = await AuthorizationService().authorize_share(
            self.db, share, permission, password_valid=password_valid
        )
        if not decision.allowed:
            await write_audit_event(
                "access_denied",
                user=None,
                resource=str(share.document_id),
                result="denied",
                operation="external_share",
                share_id=str(share.id),
                **self.context,
            )
            raise HTTPException(403, "Share unavailable")
        creator = await self.db.get(User, share.created_by)
        if creator is None:
            raise HTTPException(403, "Share unavailable")
        return share, creator

    async def consume(self, share: ExternalShare, permission: str) -> None:
        # Caller retains both locks and rechecks immediately before committing/returning bytes.
        decision = await AuthorizationService().authorize_share(
            self.db, share, permission, password_valid=True
        )
        if not decision.allowed:
            raise HTTPException(403, "Share unavailable")
        share.views += 1
        await write_audit_event(
            "download" if permission == "DOWNLOAD" else "preview",
            user=None,
            resource=str(share.document_id),
            result="success",
            operation="external_share",
            share_id=str(share.id),
            **self.context,
        )
        await self.db.commit()
