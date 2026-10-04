from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.authorization.service import AuthorizationService, utc
from app.core.config import Settings
from app.documents.service import DocumentService
from app.documents.upload import UploadService
from app.models.document import DocumentVersion
from app.models.office import OfficeRoom, OfficeSave, OfficeSession
from app.models.session import ApplicationSession
from app.models.user import User
from app.office.security import callback_download_url, configured
from app.storage.seaweed import SeaweedStorage


class OfficeService:
    def __init__(self, db: AsyncSession, settings: Settings, context: dict[str, Any]) -> None:
        self.db, self.settings, self.context = db, settings, context

    async def valid_actor(self, session: OfficeSession) -> User:
        now = datetime.now(UTC)
        application = await self.db.get(
            ApplicationSession, session.application_session_id, populate_existing=True
        )
        actor = await self.db.get(User, session.user_id, populate_existing=True)
        if (
            session.revoked_at
            or utc(session.expires_at) <= now
            or actor is None
            or not actor.enabled
            or application is None
            or application.user_id != session.user_id
            or application.revoked_at
            or utc(application.expires_at) <= now
        ):
            raise HTTPException(403, "Office session expired or revoked")
        return actor

    async def expected_current(self, room: OfficeRoom, current: DocumentVersion) -> bool:
        if current.id == room.base_version_id:
            return True
        return (
            await self.db.scalar(
                select(OfficeSave.id).where(
                    OfficeSave.room_id == room.id, OfficeSave.version_id == current.id
                )
            )
            is not None
        )

    async def open(
        self, actor: User, document_id: uuid.UUID, application: ApplicationSession
    ) -> dict[str, Any]:
        service = DocumentService(self.db, actor, self.context)
        document = await service.require(document_id, "EDIT")
        configured(self.settings)
        current = await service.current(document_id)
        extension = document.name.rsplit(".", 1)[-1].lower()
        if extension not in {"docx", "xlsx", "pptx"}:
            raise HTTPException(415, "Office format unsupported")
        if (
            application.user_id != actor.id
            or application.revoked_at
            or utc(application.expires_at) <= datetime.now(UTC)
        ):
            raise HTTPException(403, "Application session unavailable")
        room = await self.db.scalar(
            select(OfficeRoom)
            .where(OfficeRoom.document_id == document_id, OfficeRoom.closed_at.is_(None))
            .with_for_update()
        )
        now = datetime.now(UTC)
        if room and (utc(room.expires_at) <= now or not await self.expected_current(room, current)):
            room.closed_at = now
            await self.db.flush()
            room = None
        if room is None:
            pending = await self.db.scalar(
                select(OfficeSave.id)
                .join(OfficeRoom)
                .join(DocumentVersion, DocumentVersion.id == OfficeSave.version_id)
                .where(OfficeRoom.document_id == document_id, DocumentVersion.status == "PENDING")
            )
            if pending:
                raise HTTPException(409, "Office save is awaiting antivirus verification")
            room = OfficeRoom(
                id=uuid.uuid4(),
                document_id=document_id,
                base_version_id=current.id,
                expires_at=now + timedelta(seconds=self.settings.office_session_seconds),
            )
            self.db.add(room)
            await self.db.flush()
        session = OfficeSession(
            id=uuid.uuid4(),
            room_id=room.id,
            user_id=actor.id,
            application_session_id=application.id,
            expires_at=min(utc(room.expires_at), utc(application.expires_at)),
        )
        self.db.add(session)
        permissions = {}
        for name, permission in [
            ("download", "DOWNLOAD"),
            ("print", "PRINT"),
            ("copy", "CLIPBOARD_COPY"),
        ]:
            permissions[name] = (
                await AuthorizationService().authorize(self.db, actor, permission, document_id)
            ).allowed
        # ONLYOFFICE Download As includes PDF export; require both independent grants.
        permissions["download"] = (
            permissions["download"]
            and (
                await AuthorizationService().authorize(self.db, actor, "EXPORT_PDF", document_id)
            ).allowed
        )
        permissions.update({"edit": True, "comment": True, "review": True, "fillForms": False})
        base = self.settings.office_backend_url.rstrip("/") + "/api/v1/office/internal"
        config: dict[str, Any] = {
            "document": {
                "fileType": extension,
                "key": room.id.hex,
                "title": document.name,
                "url": f"{base}/content/{session.id}",
                "permissions": permissions,
            },
            "documentType": {"docx": "word", "xlsx": "cell", "pptx": "slide"}[extension],
            "editorConfig": {
                "mode": "edit",
                "callbackUrl": f"{base}/callback/{session.id}",
                "user": {"id": str(actor.id), "name": actor.display_name},
                "coEditing": {"mode": "fast", "change": False},
                "customization": {"forcesave": True},
            },
            "exp": int(utc(session.expires_at).timestamp()),
            "iat": int(now.timestamp()),
        }
        config["token"] = jwt.encode(
            config, self.settings.office_browser_secret.get_secret_value(), algorithm="HS256"
        )
        await service.audit(
            "edit", document, operation="office_open", office_session=str(session.id)
        )
        await self.db.commit()
        return {
            "config": config,
            "script_url": self.settings.office_public_url.rstrip("/")
            + "/web-apps/apps/api/documents/api.js",
            "expires_at": session.expires_at,
        }

    async def session(self, session_id: uuid.UUID) -> tuple[OfficeSession, OfficeRoom, User]:
        session = await self.db.get(OfficeSession, session_id)
        room = await self.db.get(OfficeRoom, session.room_id) if session else None
        if session is None or room is None:
            raise HTTPException(403, "Office session unavailable")
        actor = await self.valid_actor(session)
        service = DocumentService(self.db, actor, self.context)
        await service.require(room.document_id, "EDIT")  # document lock before room lock
        await self.db.refresh(room, with_for_update=True)
        if room.closed_at or utc(room.expires_at) <= datetime.now(UTC):
            raise HTTPException(403, "Office room unavailable")
        if not await self.expected_current(room, await service.current(room.document_id)):
            raise HTTPException(409, "Office base version is stale")
        return session, room, actor

    async def download(self, url: str, source: BinaryIO) -> None:
        safe_url = callback_download_url(url, self.settings)
        try:
            async with httpx.AsyncClient(
                timeout=60, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream("GET", safe_url) as response:
                    if response.status_code != 200:
                        raise HTTPException(503, "Office save unavailable")
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.upload_max_bytes:
                            raise HTTPException(413, "Office save exceeds upload limit")
                        await run_in_threadpool(source.write, chunk)
        except httpx.HTTPError:
            raise HTTPException(503, "Office save unavailable") from None
        source.seek(0)

    async def callback(
        self, session_id: uuid.UUID, payload: dict[str, Any], storage: SeaweedStorage
    ) -> dict[str, int]:
        # A durable receipt is acknowledged after signature and current actor authorization.
        existing_session = await self.db.get(OfficeSession, session_id)
        if existing_session is None:
            raise HTTPException(403, "Office session unavailable")
        actor = await self.valid_actor(existing_session)
        prior_room = await self.db.get(OfficeRoom, existing_session.room_id)
        if prior_room is None:
            raise HTTPException(403, "Office room unavailable")
        await DocumentService(self.db, actor, self.context).require(prior_room.document_id, "EDIT")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        receipt = await self.db.scalar(
            select(OfficeSave).where(
                OfficeSave.room_id == existing_session.room_id, OfficeSave.callback_hash == digest
            )
        )
        if receipt:
            return {"error": 0}
        _, room, actor = await self.session(session_id)
        if payload.get("key") != room.id.hex:
            raise HTTPException(403, "Office document key mismatch")
        status = payload.get("status")
        if type(status) is not int or status not in {1, 2, 3, 4, 6, 7}:
            raise HTTPException(422, "Invalid Office callback status")
        if status in {3, 7}:
            return {"error": 1}
        service = DocumentService(self.db, actor, self.context)
        document = await service.require(room.document_id, "EDIT")
        if status == 1:
            return {"error": 0}
        # Recheck every participant, not only the callback's last editor.
        participants = (
            await self.db.scalars(select(OfficeSession).where(OfficeSession.room_id == room.id))
        ).all()
        actors = {}
        for participant in participants:
            user = await self.valid_actor(participant)
            await DocumentService(self.db, user, self.context).require(document.id, "EDIT")
            actors[str(user.id)] = user
        version_id = None
        if status in {2, 6}:
            users = payload.get("users")
            if (
                not isinstance(users, list)
                or not users
                or any(not isinstance(u, str) or u not in actors for u in users)
            ):
                raise HTTPException(403, "Office editor identity mismatch")
            url = payload.get("url")
            if (
                not isinstance(url, str)
                or payload.get("filetype") != document.name.rsplit(".", 1)[-1].lower()
            ):
                raise HTTPException(422, "Invalid Office save format")
            with tempfile.TemporaryFile() as content:
                await self.download(url, content)
                version = await UploadService(self.db, storage).new_version(
                    actors[users[-1]],
                    document.id,
                    document.name,
                    content,
                    self.context,
                    commit=False,
                    office=True,
                )
                version_id = version.id
        if status in {2, 4}:
            room.closed_at = datetime.now(UTC)
        self.db.add(OfficeSave(room_id=room.id, callback_hash=digest, version_id=version_id))
        await service.audit(
            "edit",
            document,
            operation="office_callback",
            status=status,
            version=str(version_id) if version_id else None,
        )
        await self.db.commit()
        return {"error": 0}
