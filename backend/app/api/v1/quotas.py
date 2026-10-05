import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.resources import Actor, Db, context, require
from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.models.organization import Department
from app.models.quota import Project, QuotaLimit, StorageReservation
from app.models.resource import Resource
from app.quotas.service import QuotaService

router = APIRouter(prefix="/quotas", tags=["quotas"])


class QuotaInput(BaseModel):
    subject_type: Literal["USER", "DEPARTMENT", "PROJECT"]
    subject_id: uuid.UUID
    limit_bytes: int = Field(ge=0, le=9007199254740991)
    reason: str = Field(min_length=1, max_length=2000)


class ProjectInput(BaseModel):
    company_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)


@router.get("/me")
async def my_quota(request: Request, response: Response, db: Db, user: Actor):
    if not await AuthorizationService().account_self(db, user, user.id):
        raise HTTPException(403, "Access denied")
    service = QuotaService(db, user, context(request))
    quota = await db.get(QuotaLimit, ("USER", user.id))
    response.headers["Cache-Control"] = "no-store"
    return {
        "data": {
            "used_bytes": await service.usage("USER", user.id),
            "limit_bytes": quota.limit_bytes if quota else None,
        }
    }


@router.get("/capabilities")
async def capabilities(db: Db, user: Actor):
    return {
        "data": {
            "manage": (
                await AuthorizationService().authorize(db, user, "MANAGE_QUOTAS", None)
            ).allowed
        }
    }


@router.get("")
async def list_quotas(request: Request, response: Response, db: Db, user: Actor):
    service = QuotaService(db, user, context(request))
    await service.admin()
    response.headers["Cache-Control"] = "no-store"
    rows = (await db.scalars(select(QuotaLimit))).all()
    return {
        "data": [
            {
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "limit_bytes": row.limit_bytes,
                "used_bytes": await service.usage(row.subject_type, row.subject_id),
            }
            for row in rows
        ]
    }


@router.put("", dependencies=[Depends(require_csrf)])
async def configure_quota(payload: QuotaInput, request: Request, db: Db, user: Actor):
    row = await QuotaService(db, user, context(request)).configure(
        payload.subject_type, payload.subject_id, payload.limit_bytes, payload.reason
    )
    return {
        "data": {
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "limit_bytes": row.limit_bytes,
        }
    }


@router.get("/reservations")
async def reservations(request: Request, response: Response, db: Db, user: Actor):
    await QuotaService(db, user, context(request)).admin()
    response.headers["Cache-Control"] = "no-store"
    rows = (
        await db.scalars(select(StorageReservation).order_by(StorageReservation.created_at))
    ).all()
    return {
        "data": [
            {
                "version_id": row.version_id,
                "document_id": row.document_id,
                "size": row.size,
                "owner_id": row.owner_id,
                "area": row.area,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.get("/projects")
async def projects(request: Request, db: Db, user: Actor):
    await QuotaService(db, user, context(request)).admin()
    return {
        "data": [
            {"id": row.id, "company_id": row.company_id, "name": row.name, "enabled": row.enabled}
            for row in (await db.scalars(select(Project))).all()
        ]
    }


@router.post("/projects", status_code=201, dependencies=[Depends(require_csrf)])
async def create_project(payload: ProjectInput, request: Request, db: Db, user: Actor):
    row = await QuotaService(db, user, context(request)).create_project(
        payload.company_id, payload.name
    )
    return {"data": {"id": row.id, "name": row.name, "company_id": row.company_id}}


@router.get("/projects-for/{document_id}")
async def document_projects(document_id: uuid.UUID, db: Db, user: Actor):
    await require(db, user, "EDIT", document_id)
    row = await db.get(Resource, document_id)
    if row is None or row.resource_type != "DOCUMENT":
        raise ValueError("Document required")
    department = await db.get(Department, row.department_id)
    if department is None:
        raise HTTPException(403, "Access denied")
    rows = (
        await db.scalars(
            select(Project).where(
                Project.company_id == department.company_id, Project.enabled.is_(True)
            )
        )
    ).all()
    return {"data": [{"id": project.id, "name": project.name} for project in rows]}
