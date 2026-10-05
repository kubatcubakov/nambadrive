from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.governance.policy import governance_lock
from app.models.user import User


async def upsert_oidc_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    await governance_lock(db)
    sub = str(claims["sub"])
    username = str(claims.get("preferred_username") or claims.get("nickname") or sub)
    display_name = str(claims.get("name") or username)
    email_claim = claims.get("email")
    email = str(email_claim) if email_claim else None
    now = datetime.now(UTC)

    user = (
        await db.execute(
            select(User)
            .where(User.authentik_sub == sub)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if user is not None and not user.enabled:
        raise HTTPException(403, "Account disabled")
    if user is None:
        settings = get_settings()
        if settings.scim_token.get_secret_value() and not settings.oidc_jit_provisioning:
            raise HTTPException(403, "Account provisioning required")
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
        user.last_authentik_sync_at = now
        user.last_login_at = now
    await db.flush()
    return user
