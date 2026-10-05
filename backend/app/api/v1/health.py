from collections.abc import Awaitable
from typing import Any, cast

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import redis_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgresql"] = "ok"
    except Exception:
        checks["postgresql"] = "error"

    try:
        redis_ok = await cast(Awaitable[bool], redis_client.ping())
        checks["redis"] = "ok" if redis_ok else "error"
    except Exception:
        checks["redis"] = "error"

    overall = "ok" if all(value == "ok" for value in checks.values()) else "error"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": overall, "checks": checks}
