import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_user, require_csrf
from app.authorization.service import AuthorizationService
from app.core.database import get_db
from app.departments.service import OrganizationService
from app.models.organization import Company, Department, DepartmentManager, DepartmentMembership
from app.models.user import User

router = APIRouter(prefix="/admin/organization", tags=["organization"])


async def admin(
    db: Annotated[AsyncSession, Depends(get_db)], user: Annotated[User, Depends(current_user)]
) -> User:
    if not await AuthorizationService().organization_admin(db, user):
        raise HTTPException(403, "Organization administration required")
    return user


async def service(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin)],
) -> OrganizationService:
    return OrganizationService(
        db,
        user,
        {
            "correlation_id": request.state.correlation_id,
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
        },
    )


class CompanyInput(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"\S")


class DepartmentInput(CompanyInput):
    company_id: uuid.UUID
    parent_id: uuid.UUID | None = None


class AssignmentInput(BaseModel):
    user_id: uuid.UUID
    kind: Literal["PRIMARY", "SECONDARY", "MANAGER"]
    valid_until: AwareDatetime | None = None


@router.get("")
async def tree(svc: Annotated[OrganizationService, Depends(service)]) -> dict[str, object]:
    return {
        "data": {
            model.__tablename__: [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in (await svc.db.scalars(select(model))).all()
            ]
            for model in (Company, Department, DepartmentMembership, DepartmentManager)
        }
    }


@router.post("/companies", dependencies=[Depends(require_csrf)])
async def company(
    payload: CompanyInput, svc: Annotated[OrganizationService, Depends(service)]
) -> dict[str, object]:
    row = await svc.create_company(payload.name)
    return {"data": {"id": row.id, "name": row.name}}


@router.post("/departments", dependencies=[Depends(require_csrf)])
async def department(
    payload: DepartmentInput, svc: Annotated[OrganizationService, Depends(service)]
) -> dict[str, object]:
    row = await svc.create_department(payload.company_id, payload.name, payload.parent_id)
    return {"data": {"id": row.id, "name": row.name}}


@router.put("/departments/{department_id}/assignments", dependencies=[Depends(require_csrf)])
async def assignment(
    department_id: uuid.UUID,
    payload: AssignmentInput,
    svc: Annotated[OrganizationService, Depends(service)],
) -> dict[str, object]:
    await svc.assign(department_id, payload.user_id, payload.kind, payload.valid_until)
    return {"data": {"updated": True}}


@router.delete(
    "/departments/{department_id}/managers/{user_id}", dependencies=[Depends(require_csrf)]
)
async def revoke(
    department_id: uuid.UUID,
    user_id: uuid.UUID,
    svc: Annotated[OrganizationService, Depends(service)],
) -> dict[str, object]:
    await svc.revoke_manager(department_id, user_id)
    return {"data": {"updated": True}}
