from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import jwt
from fastapi import HTTPException

from app.core.config import Settings


def configured(settings: Settings) -> None:
    browser = settings.office_browser_secret.get_secret_value()
    outbox = settings.office_outbox_secret.get_secret_value()
    if len(browser) < 32 or len(outbox) < 32 or browser == outbox:
        raise HTTPException(503, "Office signing keys are not configured")
    for value in [
        settings.office_public_url,
        settings.office_internal_url,
        settings.office_backend_url,
    ]:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise HTTPException(503, "Office endpoints are not configured")
    if settings.app_env == "production" and urlsplit(settings.office_public_url).scheme != "https":
        raise HTTPException(503, "Office requires HTTPS")


def verify_outbox(token: str, settings: Settings) -> dict[str, Any]:
    configured(settings)
    try:
        claims = jwt.decode(
            token,
            settings.office_outbox_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "iat"]},
        )
        payload = claims.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Invalid signed payload")
        return payload
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(403, "Invalid Office signature") from None


def callback_download_url(url: str, settings: Settings) -> str:
    parsed = urlsplit(url)
    allowed = [urlsplit(settings.office_internal_url), urlsplit(settings.office_public_url)]
    if not any(
        (parsed.scheme, parsed.hostname, parsed.port) == (a.scheme, a.hostname, a.port)
        for a in allowed
    ):
        raise HTTPException(403, "Office callback origin rejected")
    path = unquote(parsed.path)
    if (
        parsed.username
        or parsed.password
        or parsed.fragment
        or not path.startswith("/cache/files/")
        or ".." in path.split("/")
        or "\\" in path
        or len(url) > 4096
    ):
        raise HTTPException(403, "Office callback URL rejected")
    # Always contact the configured internal origin, never DNS supplied by the callback.
    internal = urlsplit(settings.office_internal_url)
    return urlunsplit((internal.scheme, internal.netloc, parsed.path, parsed.query, ""))
