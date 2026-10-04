from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def upsert_oidc_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    sub = str(claims["sub"])
    username = str(claims.get("preferred_username") or claims.get("nickname") or sub)
    display_name = str(claims.get("name") or username)
    email_claim = claims.get("email")
    email = str(email_claim) if email_claim else None
    now = datetime.now(UTC)

    user = (await db.execute(select(User).where(User.authentik_sub == sub))).scalar_one_or_none()
    if user is None:
        user = User(
            authentik_sub=sub,
            username=username,
            display_name=display_name,
            email=email,
            enabled=True,
            last_authentik_sync_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.username = username
        user.display_name = display_name
        user.email = email
        user.enabled = True
        user.last_authentik_sync_at = now
        user.last_login_at = now
    await db.flush()
    return user
