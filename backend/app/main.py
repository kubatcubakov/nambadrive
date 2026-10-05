import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.scim import router as scim_router
from app.api.v1.access_requests import router as access_requests_router
from app.api.v1.access_reviews import router as access_reviews_router
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.drive import router as drive_router
from app.api.v1.governance import router as governance_router
from app.api.v1.health import router as health_router
from app.api.v1.lifecycle import router as lifecycle_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.office import router as office_router
from app.api.v1.organization import router as organization_router
from app.api.v1.quotas import router as quotas_router
from app.api.v1.resources import router as resources_router
from app.api.v1.search import router as search_router
from app.api.v1.shares import router as shares_router
from app.audit.context import audit_context
from app.audit.writer import write_audit_event
from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import redis_client
from app.search.clients import SearchUnavailable
from app.storage.seaweed import StorageError

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    lifespan=lifespan,
)

app.include_router(drive_router, prefix=settings.api_v1_prefix)
app.include_router(scim_router)
app.include_router(lifecycle_router, prefix=settings.api_v1_prefix)
app.include_router(notifications_router, prefix=settings.api_v1_prefix)
app.include_router(access_reviews_router, prefix=settings.api_v1_prefix)
app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(governance_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(access_requests_router, prefix=settings.api_v1_prefix)
app.include_router(documents_router, prefix=settings.api_v1_prefix)
app.include_router(office_router, prefix=settings.api_v1_prefix)
app.include_router(search_router, prefix=settings.api_v1_prefix)
app.include_router(shares_router, prefix=settings.api_v1_prefix)


app.include_router(organization_router, prefix=settings.api_v1_prefix)


@app.exception_handler(ValueError)
async def invalid_input(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_INPUT",
                "message": str(exc),
                "correlation_id": request.state.correlation_id,
            }
        },
    )


@app.exception_handler(IntegrityError)
async def conflict(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "CONFLICT",
                "message": "Operation conflicts with existing data",
                "correlation_id": request.state.correlation_id,
            }
        },
    )


app.include_router(resources_router, prefix=settings.api_v1_prefix)
app.include_router(quotas_router, prefix=settings.api_v1_prefix)


@app.middleware("http")
async def correlation(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    try:
        correlation_id = str(uuid.UUID(request.headers.get("X-Correlation-ID", "")))
    except ValueError:
        correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    token = audit_context.set(
        {
            "correlation_id": correlation_id,
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
        }
    )
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    finally:
        audit_context.reset(token)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code in {401, 403}:
        try:
            await write_audit_event(
                "access_denied",
                result="denied",
                status=exc.status_code,
                method=request.method,
                route=getattr(request.scope.get("route"), "path", "unmatched"),
            )
        except OSError as error:
            return await unavailable(request, error)
    if request.url.path.startswith("/scim/v2/"):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                "status": str(exc.status_code),
                "detail": str(exc.detail),
            },
            media_type="application/scim+json",
        )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": "HTTP_" + str(exc.status_code),
                "message": str(exc.detail),
                "correlation_id": request.state.correlation_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith("/scim/v2/"):
        return JSONResponse(
            status_code=400,
            content={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                "status": "400",
                "scimType": "invalidValue",
                "detail": "Request validation failed",
            },
            media_type="application/scim+json",
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_INPUT",
                "message": "Request validation failed",
                "correlation_id": request.state.correlation_id,
            }
        },
    )


@app.exception_handler(SearchUnavailable)
@app.exception_handler(StorageError)
@app.exception_handler(SQLAlchemyError)
@app.exception_handler(OSError)
async def unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Operation could not be completed",
                "correlation_id": request.state.correlation_id,
            }
        },
    )
