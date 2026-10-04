import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.office import router as office_router
from app.api.v1.organization import router as organization_router
from app.api.v1.resources import router as resources_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import redis_client
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

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(documents_router, prefix=settings.api_v1_prefix)
app.include_router(office_router, prefix=settings.api_v1_prefix)


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


@app.middleware("http")
async def correlation(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    try:
        correlation_id = str(uuid.UUID(request.headers.get("X-Correlation-ID", "")))
    except ValueError:
        correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
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
