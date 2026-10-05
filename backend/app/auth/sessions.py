from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import random_urlsafe, sha256_hex
from app.core.config import Settings
from app.governance.policy import governance_lock, utc
from app.models.session import ApplicationSession
from app.models.user import User


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
) -> str:
    await governance_lock(db)
    enabled = await db.scalar(
        select(User.id).where(User.id == user.id, User.enabled.is_(True)).with_for_update()
    )
    if enabled is None:
        raise HTTPException(403, "Account disabled")
    raw_token = random_urlsafe(48)
    now = datetime.now(UTC)
    session = ApplicationSession(
        user_id=user.id,
        session_hash=sha256_hex(raw_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        ip=ip,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return raw_token


async def get_session_user(
    db: AsyncSession,
    raw_token: str,
) -> tuple[ApplicationSession, User] | None:
    now = datetime.now(UTC)
    stmt = (
        select(ApplicationSession, User)
        .join(User, User.id == ApplicationSession.user_id)
        .where(
            ApplicationSession.session_hash == sha256_hex(raw_token),
            ApplicationSession.revoked_at.is_(None),
            ApplicationSession.expires_at > now,
            User.enabled.is_(True),
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    session, user = row
    if (now - utc(session.last_seen_at)).total_seconds() >= 300:
        session.last_seen_at = now
    return session, user


async def revoke_session(db: AsyncSession, raw_token: str) -> bool:
    now = datetime.now(UTC)
    stmt = select(ApplicationSession).where(
        ApplicationSession.session_hash == sha256_hex(raw_token),
        ApplicationSession.revoked_at.is_(None),
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        return False
    session.revoked_at = now
    return True


async def revoke_all_user_sessions(db: AsyncSession, user: User) -> int:
    now = datetime.now(UTC)
    count = 0
    for session in user.sessions:
        if session.revoked_at is None and session.expires_at > now:
            session.revoked_at = now
            count += 1
    return count
