from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit_event
from app.auth.csrf import csrf_token
from app.auth.dependencies import current_user, require_csrf
from app.auth.oidc import OIDCClient, OIDCError
from app.auth.sessions import create_session, revoke_session
from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import AuthMeResponse, UserProfile
from app.users.service import upsert_oidc_user

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
oidc = OIDCClient(settings)


def client_ip(request: Request) -> str | None:
    # Uvicorn's trusted proxy configuration supplies the verified client address.
    # Never consume arbitrary user-supplied X-Forwarded-For here.
    return request.client.host if request.client else None


@router.get("/login")
async def login(next_url: str = Query(default="/")) -> RedirectResponse:
    if not settings.oidc_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC is not configured"
        )
    try:
        transaction, authorization_url = await oidc.start_login(next_url=next_url)
    except (OIDCError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC provider unavailable"
        ) from exc
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.oidc_state_cookie_name,
        transaction.state,
        max_age=settings.oidc_transaction_ttl_seconds,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/api/v1/auth/callback",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str,
    state: str,
    oidc_state: Annotated[str | None, Cookie(alias=settings.oidc_state_cookie_name)] = None,
) -> Response:
    if not oidc_state or oidc_state != state:
        await write_audit_event("login_failed", reason="oidc_state_mismatch", ip=client_ip(request))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OIDC state")

    try:
        transaction = await oidc.consume_transaction(state)
        token_response = await oidc.exchange_code(code, transaction.code_verifier)
        id_token = token_response.get("id_token")
        if not id_token:
            raise OIDCError("OIDC provider did not return id_token")
        claims = await oidc.validate_id_token(str(id_token), transaction.nonce)
    except (OIDCError, httpx.HTTPError, ValueError) as exc:
        await db.rollback()
        await write_audit_event(
            "login_failed",
            reason="oidc_validation_failed",
            ip=client_ip(request),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC login failed"
        ) from exc

    user = await upsert_oidc_user(db, claims)
    session_token = await create_session(
        db,
        user=user,
        settings=settings,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await write_audit_event(
        "login",
        user_id=str(user.id),
        username=user.username,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        result="success",
    )

    await db.commit()
    response = RedirectResponse(transaction.next_url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(settings.oidc_state_cookie_name, path="/api/v1/auth/callback")
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/csrf")
async def csrf(
    _user: Annotated[User, Depends(current_user)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, dict[str, str]]:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return {"data": {"csrf_token": csrf_token(session_token, settings)}}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
    user: Annotated[User, Depends(current_user)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> Response:
    if session_token:
        await revoke_session(db, session_token)
        await db.commit()
    await write_audit_event(
        "logout",
        user_id=str(user.id),
        username=user.username,
        ip=client_ip(request),
        result="success",
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me", response_model=AuthMeResponse)
async def me(user: Annotated[User, Depends(current_user)]) -> AuthMeResponse:
    return AuthMeResponse(data=UserProfile.model_validate(user))
