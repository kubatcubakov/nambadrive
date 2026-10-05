from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_user, require_csrf
from app.authorization.administration import ACLAdministrationService
from app.authorization.service import AuthorizationService
from app.core.database import get_db
from app.models.acl import ACLEntry, RoleBinding
from app.models.resource import Resource
from app.models.user import User
from app.resources.service import ResourceService

router = APIRouter(prefix="/resources", tags=["resources"])
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def context(request: Request) -> dict[str, object]:
    return {
        "correlation_id": getattr(request.state, "correlation_id", str(uuid.uuid4())),
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
    }


def serialize(row: Resource | ACLEntry | RoleBinding) -> dict[str, object]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


async def require(
    db: AsyncSession, user: User, permission: str, resource_id: uuid.UUID | None
) -> None:
    result = await AuthorizationService().authorize(db, user, permission, resource_id)
    if not result.allowed:
        raise HTTPException(403, "Access denied")


class ResourceInput(BaseModel):
    resource_type: Literal["SPACE", "FOLDER", "DOCUMENT"]
    name: str = Field(min_length=1, max_length=255)
    department_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    inherit_acl: bool = True
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"] = (
        "INTERNAL"
    )


class ACLInput(BaseModel):
    principal_type: Literal["USER", "DEPARTMENT", "ROLE"]
    principal_id: uuid.UUID
    permission: str = Field(max_length=40)
    effect: Literal["ALLOW", "DENY"]
    applies_to_self: bool = True
    propagate_to_children: bool = False
    reason: str = Field(min_length=1, max_length=2000)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class BreakGlassInput(BaseModel):
    permission: str
    reason: str = Field(min_length=1, max_length=2000)
    minutes: int = Field(ge=1, le=60)


@router.get("")
async def list_resources(
    db: Db, user: Actor, parent_id: uuid.UUID | None = None
) -> dict[str, object]:
    # Return only authorized metadata; no counts of inaccessible candidates.
    query = select(Resource).where(Resource.parent_id == parent_id).order_by(Resource.id)
    visible = []
    for row in (await db.scalars(query)).all():
        if (await AuthorizationService().authorize(db, user, "VIEW", row.id)).allowed:
            visible.append(serialize(row))
    return {"data": visible}


@router.get("/{resource_id}")
async def get_resource(resource_id: uuid.UUID, db: Db, user: Actor) -> dict[str, object]:
    await require(db, user, "VIEW", resource_id)
    row = await db.get(Resource, resource_id)
    if row is None:
        raise HTTPException(404, "Resource unavailable")
    return {"data": serialize(row)}


@router.post("", dependencies=[Depends(require_csrf)])
async def create_resource(
    payload: ResourceInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    from app.governance.policy import governance_lock

    await governance_lock(db)
    permission = (
        "CREATE_SPACE"
        if payload.resource_type == "SPACE"
        else ("CREATE_FOLDER" if payload.resource_type == "FOLDER" else "CREATE")
    )
    if payload.parent_id:
        await db.get(Resource, payload.parent_id, with_for_update=True)
    await require(db, user, permission, payload.parent_id)
    row = await ResourceService(db, user, context(request)).create(**payload.model_dump())
    return {"data": serialize(row)}


@router.get("/{resource_id}/permissions/{permission}")
async def permission_decision(
    resource_id: uuid.UUID, permission: str, db: Db, user: Actor
) -> dict[str, object]:
    # Resource metadata and decision reasons are visible only after a VIEW check.
    await require(db, user, "VIEW", resource_id)
    return {
        "data": asdict(await AuthorizationService().authorize(db, user, permission, resource_id))
    }


@router.get("/{resource_id}/acl")
async def list_acl(
    resource_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    entries = await ACLAdministrationService(db, user, context(request)).list_entries(resource_id)
    return {"data": [serialize(entry) for entry in entries]}


@router.post("/{resource_id}/acl", dependencies=[Depends(require_csrf)])
async def create_acl(
    resource_id: uuid.UUID, payload: ACLInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    entry = await ACLAdministrationService(db, user, context(request)).grant(
        resource_id, **payload.model_dump()
    )
    return {"data": serialize(entry)}


@router.delete("/{resource_id}/acl/{entry_id}", dependencies=[Depends(require_csrf)])
async def revoke_acl(
    resource_id: uuid.UUID, entry_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    await ACLAdministrationService(db, user, context(request)).revoke(resource_id, entry_id)
    return {"data": {"revoked": True}}


@router.post("/{resource_id}/break-glass", dependencies=[Depends(require_csrf)])
async def break_glass(
    resource_id: uuid.UUID, payload: BreakGlassInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    grant = await ACLAdministrationService(db, user, context(request)).break_glass(
        resource_id, **payload.model_dump()
    )
    return {"data": {"id": grant.id, "valid_until": grant.valid_until}}


class BindingInput(BaseModel):
    user_id: uuid.UUID
    role_name: Literal["EDITOR", "REVIEWER", "READER", "GUEST"]
    valid_until: AwareDatetime | None = None


@router.get("/{resource_id}/role-bindings")
async def list_bindings(
    resource_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    await ACLAdministrationService(db, user, context(request)).require(resource_id)
    rows = (
        await db.scalars(select(RoleBinding).where(RoleBinding.resource_id == resource_id))
    ).all()
    return {"data": [serialize(row) for row in rows]}


@router.post("/{resource_id}/role-bindings", dependencies=[Depends(require_csrf)])
async def bind_role(
    resource_id: uuid.UUID, payload: BindingInput, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    row = await ACLAdministrationService(db, user, context(request)).bind_role(
        resource_id, **payload.model_dump()
    )
    return {"data": serialize(row)}


@router.delete("/{resource_id}/role-bindings/{binding_id}", dependencies=[Depends(require_csrf)])
async def revoke_binding(
    resource_id: uuid.UUID, binding_id: uuid.UUID, request: Request, db: Db, user: Actor
) -> dict[str, object]:
    await ACLAdministrationService(db, user, context(request)).revoke_binding(
        resource_id, binding_id
    )
    return {"data": {"revoked": True}}


class SecurityInput(BaseModel):
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"]
    inherit_acl: bool
    reason: str = Field(min_length=1, max_length=2000)


@router.put("/{resource_id}/security", dependencies=[Depends(require_csrf)])
async def security_policy(
    resource_id: uuid.UUID, payload: SecurityInput, request: Request, db: Db, user: Actor
):
    from datetime import UTC, datetime

    from app.audit.writer import write_audit_event
    from app.governance.policy import chain, governance_lock
    from app.models.share import ExternalShare

    await governance_lock(db)
    await ACLAdministrationService(db, user, context(request)).require(resource_id)
    if not payload.reason.strip():
        raise ValueError("Reason required")
    resource = await db.get(Resource, resource_id, populate_existing=True)
    if resource is None:
        raise HTTPException(404, "Resource unavailable")
    old = {"classification": resource.classification, "inherit_acl": resource.inherit_acl}
    changed = resource.classification != payload.classification
    resource.classification, resource.inherit_acl = payload.classification, payload.inherit_acl
    # A classification change never revives links issued under an older policy.
    if changed:
        shares = (
            await db.scalars(
                select(ExternalShare).where(ExternalShare.revoked_at.is_(None)).with_for_update()
            )
        ).all()
        for share in shares:
            if resource_id in {r.id for r in await chain(db, share.document_id)}:
                share.revoked_at = datetime.now(UTC)
                await write_audit_event(
                    "share",
                    user=str(user.id),
                    resource=str(share.document_id),
                    result="success",
                    operation="revoke_classification_change",
                    share_id=str(share.id),
                    **context(request),
                )
    await write_audit_event(
        "classification_changed" if changed else "change_acl",
        user=str(user.id),
        resource=str(resource.id),
        result="success",
        reason=payload.reason,
        old_acl=old,
        new_acl=payload.model_dump(exclude={"reason"}),
        **context(request),
    )
    await db.commit()
    return {
        "data": {"classification": resource.classification, "inherit_acl": resource.inherit_acl}
    }


@router.get("/{resource_id}/capabilities")
async def resource_capabilities(resource_id: uuid.UUID, db: Db, user: Actor):
    from app.authorization.catalog import PERMISSIONS

    await require(db, user, "VIEW", resource_id)
    authorization = AuthorizationService()
    allowed = []
    for permission in sorted(PERMISSIONS):
        if (await authorization.authorize(db, user, permission, resource_id)).allowed:
            allowed.append(permission)
    return {"data": allowed}
