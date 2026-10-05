"""SCIM 2.0 Users backchannel: externalId MUST equal immutable OIDC sub."""

from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization.service import AuthorizationService
from app.core.config import get_settings
from app.core.database import get_db
from app.lifecycle.service import LifecycleService
from app.models.user import User

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
Db = Annotated[AsyncSession, Depends(get_db)]


async def integration(authorization: Annotated[str | None, Header()] = None) -> None:
    configured = get_settings().scim_token.get_secret_value()
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not AuthorizationService.identity_integration(configured, supplied):
        raise HTTPException(401, "Provisioning authentication required")


class ScimResponse(JSONResponse):
    media_type = "application/scim+json"


router = APIRouter(
    prefix="/scim/v2",
    tags=["scim"],
    dependencies=[Depends(integration)],
    default_response_class=ScimResponse,
)


class ScimEmail(BaseModel):
    value: str = Field(max_length=254)
    primary: StrictBool = False


class ScimUser(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: [USER_SCHEMA], max_length=10)
    externalId: str = Field(min_length=1, max_length=255)
    userName: str = Field(min_length=1, max_length=150)
    displayName: str | None = Field(default=None, max_length=255)
    active: StrictBool
    emails: list[ScimEmail] = Field(default_factory=list, max_length=10)


def representation(user: User) -> dict[str, Any]:
    return {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "externalId": user.authentik_sub,
        "userName": user.username,
        "displayName": user.display_name,
        "active": user.enabled,
        "emails": [{"value": user.email, "primary": True}] if user.email else [],
        "meta": {"resourceType": "User", "location": "/scim/v2/Users/" + str(user.id)},
    }


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@router.get("/ServiceProviderConfig")
async def config():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": False},
        "bulk": {"supported": False},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Provisioning bearer token",
                "description": "Private Authentik backchannel",
                "primary": True,
            }
        ],
    }


@router.get("/Users")
async def users(
    db: Db,
    response: Response,
    filter: str | None = Query(default=None, max_length=1024),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=100),
):
    query = select(User)
    if filter is not None:
        match = re.fullmatch(r'(externalId|userName)\s+eq\s+("(?:[^"\\]|\\.)*")', filter)
        if not match:
            raise HTTPException(400, "Unsupported identity filter")
        value = json.loads(match[2])
        column = User.authentik_sub if match[1] == "externalId" else User.username
        query = query.where(column == value)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(User.id).offset(startIndex - 1).limit(count))).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(rows),
        "Resources": [representation(u) for u in rows],
    }


@router.get("/Users/{user_id}")
async def detail(user_id: uuid.UUID, db: Db, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return representation(await get_user(db, user_id))


async def synchronize(payload: ScimUser, db: AsyncSession, expected: uuid.UUID | None = None):
    if USER_SCHEMA not in payload.schemas:
        raise HTTPException(400, "Unsupported schema")
    emails = sorted(payload.emails, key=lambda e: not e.primary)
    user = await LifecycleService(db, "authentik_scim").synchronize(
        payload.externalId,
        payload.userName,
        payload.displayName or payload.userName,
        emails[0].value if emails else None,
        payload.active,
        expected_id=expected,
    )
    return representation(user)


@router.post("/Users", status_code=201)
async def create(payload: ScimUser, db: Db, response: Response):
    from app.governance.policy import governance_lock

    await governance_lock(db)
    if await db.scalar(select(User.id).where(User.authentik_sub == payload.externalId)):
        raise HTTPException(409, "Identity already provisioned")
    data = await synchronize(payload, db)
    response.headers["Location"] = data["meta"]["location"]
    response.headers["Cache-Control"] = "no-store"
    return data


@router.put("/Users/{user_id}")
async def replace(user_id: uuid.UUID, payload: ScimUser, db: Db, response: Response):
    await get_user(db, user_id)
    response.headers["Cache-Control"] = "no-store"
    return await synchronize(payload, db, user_id)


@router.delete("/Users/{user_id}", status_code=204)
async def delete(user_id: uuid.UUID, db: Db):
    from app.governance.policy import governance_lock

    await governance_lock(db)
    user = await get_user(db, user_id)
    await LifecycleService(db, "authentik_scim").disable(user)
    await db.commit()
    return Response(status_code=204)


@router.get("/ResourceTypes")
async def resource_types():
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": 1,
        "startIndex": 1,
        "itemsPerPage": 1,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": USER_SCHEMA,
            }
        ],
    }


@router.get("/Schemas")
async def schemas():
    attributes = [
        {
            "name": name,
            "type": kind,
            "multiValued": False,
            "required": required,
            "mutability": mutability,
            "returned": "default",
            "uniqueness": uniqueness,
        }
        for name, kind, required, mutability, uniqueness in [
            ("externalId", "string", True, "immutable", "server"),
            ("userName", "string", True, "readWrite", "none"),
            ("displayName", "string", False, "readWrite", "none"),
            ("active", "boolean", True, "readWrite", "none"),
        ]
    ]
    attributes.append(
        {
            "name": "emails",
            "type": "complex",
            "multiValued": True,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "uniqueness": "none",
            "subAttributes": [
                {"name": "value", "type": "string", "multiValued": False},
                {"name": "primary", "type": "boolean", "multiValued": False},
            ],
        }
    )
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": 1,
        "startIndex": 1,
        "itemsPerPage": 1,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
                "id": USER_SCHEMA,
                "name": "User",
                "attributes": attributes,
            }
        ],
    }
