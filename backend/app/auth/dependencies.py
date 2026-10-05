from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import audit_context
from app.auth.csrf import csrf_valid
from app.auth.sessions import get_session_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User

settings = get_settings()


async def current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    result = await get_session_user(db, session_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid or expired"
        )
    _, user = result
    context = audit_context.get()
    if context is not None:
        context["user"] = str(user.id)
    return user


async def require_csrf(
    _user: Annotated[User, Depends(current_user)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
    supplied_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if (
        not session_token
        or not supplied_token
        or not csrf_valid(session_token, supplied_token, settings)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
