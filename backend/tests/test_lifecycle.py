import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.auth.sessions import create_session, get_session_user
from app.authorization.service import AuthorizationService
from app.core.config import Settings
from app.lifecycle.service import LifecycleService
from app.main import app
from app.models.acl import RoleBinding
from app.models.lifecycle import OwnershipTransfer
from app.models.organization import DepartmentManager, OrganizationAdministrator
from app.models.resource import Resource
from app.models.user import User
from app.users.service import upsert_oidc_user
from tests.test_authorization import acl, binding
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture

api, clean, scene, admin = api_fixture, clean_fixture, scene_fixture, admin_fixture
TOKEN = "A" * 64


@pytest.fixture
async def scim(api, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "scim_token", SecretStr(TOKEN))
    return api[0]


def payload(user, enabled):
    return {
        "externalId": user.authentik_sub,
        "userName": user.username,
        "displayName": user.display_name,
        "active": enabled,
    }


async def test_scim_authentication_and_immutable_identity(scim, db, scene):
    owner = scene[0]
    path = "/scim/v2/Users/" + str(owner.id)
    assert (await scim.put(path, json=payload(owner, False))).status_code == 401
    headers = {"Authorization": "Bearer " + TOKEN}
    assert (await scim.get("/scim/v2/ServiceProviderConfig", headers=headers)).status_code == 200
    body = payload(owner, False) | {"externalId": "attacker-other-sub"}
    assert (await scim.put(path, json=body, headers=headers)).status_code == 409
    assert (await db.get(User, owner.id)).enabled
    body = payload(owner, True) | {"userName": "renamed", "emails": [{"value": "new@example.com"}]}
    response = await scim.put(path, json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(owner.id)
    assert response.json()["externalId"] == owner.authentik_sub
    assert response.json()["userName"] == "renamed"
    assert (await scim.post("/scim/v2/Users", json=body, headers=headers)).status_code == 409
    body["active"] = "false"
    assert (await scim.put(path, json=body, headers=headers)).status_code == 400


async def test_scim_provisions_only_immutable_sub_not_email(scim, db, scene):
    headers = {"Authorization": "Bearer " + TOKEN}
    body = payload(scene[0], True) | {"externalId": "new-immutable-sub"}
    result = await scim.post("/scim/v2/Users", json=body, headers=headers)
    assert result.status_code == 201 and result.json()["id"] != str(scene[0].id)
    assert result.headers["Cache-Control"] == "no-store"
    result = await scim.get(
        "/scim/v2/Users", params={"filter": 'externalId eq "new-immutable-sub"'}, headers=headers
    )
    assert result.json()["totalResults"] == 1
    assert (
        await scim.get(
            "/scim/v2/Users", params={"filter": "userName pr or active eq true"}, headers=headers
        )
    ).status_code == 400
    user_id = result.json()["Resources"][0]["id"]
    assert (await scim.delete("/scim/v2/Users/" + user_id, headers=headers)).status_code == 204
    assert not (await scim.get("/scim/v2/Users/" + user_id, headers=headers)).json()["active"]


async def test_disable_revokes_sessions_direct_acl_roles_and_manager_then_no_oidc_reenable(
    db, scene
):
    owner, outsider = scene[:2]
    token = await create_session(db, user=outsider, settings=Settings(), ip=None, user_agent=None)
    grant = await acl(
        db, scene, subject=outsider.id, valid_from=datetime.now(UTC) - timedelta(days=1)
    )
    await binding(
        db,
        outsider,
        "READER",
        resource_id=scene[2].id,
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    manager = DepartmentManager(
        user_id=outsider.id,
        department_id=scene[5].id,
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    db.add_all([manager, OrganizationAdministrator(user_id=outsider.id)])
    await db.commit()
    await LifecycleService(db, "authentik_scim").synchronize(
        outsider.authentik_sub, outsider.username, outsider.display_name, None, False
    )
    assert not outsider.enabled and grant.revoked_at and manager.revoked_at
    assert await get_session_user(db, token) is None
    assert (
        await db.scalar(select(RoleBinding).where(RoleBinding.user_id == outsider.id))
    ).revoked_at
    assert await db.get(OrganizationAdministrator, outsider.id) is None
    with pytest.raises(HTTPException) as error:
        await upsert_oidc_user(db, {"sub": outsider.authentik_sub})
    assert error.value.status_code == 403
    await LifecycleService(db, "authentik_scim").synchronize(
        outsider.authentik_sub, outsider.username, outsider.display_name, None, True
    )
    assert outsider.enabled and await get_session_user(db, token) is None
    assert not (await AuthorizationService().authorize(db, outsider, "VIEW", scene[4].id)).allowed
    assert owner.enabled


async def test_department_then_space_then_global_fallback_preserves_governance(db, scene, admin):
    owner, successor, space, folder, document, department, child = scene
    db.add(
        DepartmentManager(
            user_id=successor.id,
            department_id=department.id,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
    )
    document.legal_hold = True
    document.retention_until = datetime.now(UTC) + timedelta(days=365)
    document.classification = "STRICTLY_CONFIDENTIAL"
    await db.commit()
    await LifecycleService(db, "authentik_scim").synchronize(
        owner.authentik_sub, owner.username, owner.display_name, None, False
    )
    for resource in [space, folder, document]:
        assert resource.owner_user_id == successor.id
    assert (
        document.legal_hold
        and document.retention_until
        and document.classification == "STRICTLY_CONFIDENTIAL"
    )
    assert not (await db.scalars(select(OwnershipTransfer))).all()
    # Last owner disabled without successor: account still disabled; durable work remains.
    await LifecycleService(db, "authentik_scim").synchronize(
        successor.authentik_sub, successor.username, successor.display_name, None, False
    )
    assert not successor.enabled
    assert len((await db.scalars(select(OwnershipTransfer))).all()) == 3
    await LifecycleService(db, str(admin.id)).configure(admin, admin.id, "Approved global fallback")
    for resource in [space, folder, document]:
        assert resource.owner_user_id == admin.id
    assert not (await db.scalars(select(OwnershipTransfer))).all()


async def test_space_owner_fallback(db, scene):
    owner, outsider, space, folder, document, *_ = scene
    document.owner_user_id = outsider.id
    await db.commit()
    await LifecycleService(db, "authentik_scim").synchronize(
        outsider.authentik_sub, outsider.username, outsider.display_name, None, False
    )
    assert document.owner_user_id == owner.id
    assert space.owner_user_id == owner.id and folder.owner_user_id == owner.id


async def test_disabled_login_provisioning_and_token_fail_closed(db, scene, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "scim_token", SecretStr(TOKEN))
    with pytest.raises(HTTPException):
        await upsert_oidc_user(db, {"sub": "unknown-not-provisioned"})
    assert not AuthorizationService.identity_integration("", "")
    assert not AuthorizationService.identity_integration("short", "short")
    assert not AuthorizationService.identity_integration(TOKEN, TOKEN + "x")
    assert AuthorizationService.identity_integration(TOKEN, TOKEN)


async def test_oidc_jit_creates_identity_without_grants_with_scim_enabled(db, scene, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "scim_token", SecretStr(TOKEN))
    monkeypatch.setattr(get_settings(), "oidc_jit_provisioning", True)
    owner = scene[0]
    # Matching a profile must never bind to that user's immutable identity.
    account = await upsert_oidc_user(
        db,
        {
            "sub": "new-jit-immutable-sub",
            "preferred_username": owner.username,
            "email": owner.email,
            "name": "New JIT user",
        },
    )
    assert account.id != owner.id
    assert account.authentik_sub == "new-jit-immutable-sub" and account.enabled
    assert not (
        await db.scalars(select(RoleBinding).where(RoleBinding.user_id == account.id))
    ).all()
    assert not (
        await db.scalars(
            select(OrganizationAdministrator).where(OrganizationAdministrator.user_id == account.id)
        )
    ).all()
    assert not (
        await db.scalars(select(DepartmentManager).where(DepartmentManager.user_id == account.id))
    ).all()
    assert not (await AuthorizationService().authorize(db, account, "VIEW", scene[4].id)).allowed
    assert not (
        await AuthorizationService().authorize(db, account, "DOWNLOAD", scene[4].id)
    ).allowed
    again = await upsert_oidc_user(
        db, {"sub": account.authentik_sub, "preferred_username": "renamed-jit"}
    )
    assert again.id == account.id and again.username == "renamed-jit"


async def test_oidc_jit_cannot_reenable_scim_disabled_identity(db, scene, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "scim_token", SecretStr(TOKEN))
    monkeypatch.setattr(get_settings(), "oidc_jit_provisioning", True)
    account = await upsert_oidc_user(db, {"sub": "jit-disabled-sub"})
    await LifecycleService(db, "authentik_scim").synchronize(
        account.authentik_sub, account.username, account.display_name, None, False
    )
    with pytest.raises(HTTPException) as error:
        await upsert_oidc_user(db, {"sub": account.authentik_sub})
    assert error.value.status_code == 403 and error.value.detail == "Account disabled"
    assert not account.enabled


async def test_identity_admin_has_no_content_authority_and_requires_csrf(api, db, scene, admin):
    client, state = api
    assert (await client.get("/api/v1/identity")).status_code == 403
    state["actor"] = admin
    assert (await client.get("/api/v1/identity")).status_code == 200
    assert not (await AuthorizationService().authorize(db, admin, "VIEW", scene[4].id)).allowed
    path = "/api/v1/identity/policy"
    body = {"global_owner_id": str(scene[1].id), "reason": "approved"}
    assert (await client.put(path, json=body)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (await client.put(path, json=body)).status_code == 200


async def test_disable_audit_failure_rolls_back_all_changes(db, scene):
    user = scene[0]
    user_id, resource_id = user.id, scene[4].id
    await db.commit()
    with patch(
        "app.lifecycle.service.write_audit_event", new=AsyncMock(side_effect=OSError("full"))
    ):
        with pytest.raises(OSError):
            await LifecycleService(db, "authentik_scim").synchronize(
                user.authentik_sub, user.username, user.display_name, None, False
            )
    await db.rollback()
    assert (await db.get(User, user_id)).enabled
    assert (await db.get(Resource, resource_id)).owner_user_id == user_id
    assert not (await db.scalars(select(OwnershipTransfer))).all()


@pytest.mark.skipif(os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1", reason="PostgreSQL runtime")
async def test_postgres_disable_serializes_with_oidc_login():
    # Two independent committed connections, unlike the rollback fixture.
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from tests.test_organization import user as new_user

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as setup:
            account = await new_user(setup)
            await setup.commit()
            account_id, sub = account.id, account.authentik_sub

        async def disable():
            async with factory() as session:
                await LifecycleService(session, "authentik_scim").synchronize(
                    sub, "user", "User", None, False
                )

        async def login():
            async with factory() as session:
                try:
                    account = await upsert_oidc_user(session, {"sub": sub})
                    token = await create_session(
                        session, user=account, settings=Settings(), ip=None, user_agent=None
                    )
                    await session.commit()
                    return token
                except HTTPException:
                    return None

        _, token = await asyncio.gather(disable(), login())
        async with factory() as verify:
            assert not (await verify.get(User, account_id)).enabled
            if token:
                assert await get_session_user(verify, token) is None
            from sqlalchemy import delete

            from app.models.session import ApplicationSession

            await verify.execute(
                delete(ApplicationSession).where(ApplicationSession.user_id == account_id)
            )
            await verify.execute(delete(User).where(User.id == account_id))
            await verify.commit()
    finally:
        await engine.dispose()


async def test_disable_revokes_external_capability_office_and_breakglass(db, scene, clean):
    import uuid

    from app.models.acl import BreakGlassGrant
    from app.models.office import OfficeRoom, OfficeSession
    from app.models.session import ApplicationSession
    from app.models.share import ExternalShare
    from app.shares.service import ShareService

    owner = scene[0]
    document, version, _ = clean
    for resource in [scene[2], scene[3], document]:
        resource.classification = "PUBLIC"
    await create_session(db, user=owner, settings=Settings(), ip=None, user_agent=None)
    session = await db.scalar(
        select(ApplicationSession).where(ApplicationSession.user_id == owner.id)
    )
    room = OfficeRoom(
        id=uuid.uuid4(),
        document_id=document.id,
        base_version_id=version.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(room)
    await db.flush()
    office = OfficeSession(
        room_id=room.id,
        user_id=owner.id,
        application_session_id=session.id,
        expires_at=room.expires_at,
    )
    emergency = BreakGlassGrant(
        user_id=owner.id,
        resource_id=document.id,
        permission_id="VIEW",
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
        created_by=owner.id,
        reason="test",
        audited=True,
    )
    db.add_all([office, emergency])
    await db.commit()
    share, token = await ShareService(db, {}).create(owner, document.id)
    await LifecycleService(db, "authentik_scim").synchronize(
        owner.authentik_sub, owner.username, owner.display_name, None, False
    )
    assert office.revoked_at and emergency.revoked_at
    assert (await db.get(ExternalShare, share.id)).revoked_at
    with pytest.raises(HTTPException):
        await ShareService(db, {}).resolve(token, None, "PREVIEW")
    with pytest.raises(HTTPException):
        await create_session(db, user=owner, settings=Settings(), ip=None, user_agent=None)


async def test_reenabled_account_cannot_reclaim_pending_ownership(db, scene, admin):
    owner = scene[0]
    await LifecycleService(db, "authentik_scim").synchronize(
        owner.authentik_sub, owner.username, owner.display_name, None, False
    )
    assert len((await db.scalars(select(OwnershipTransfer))).all()) == 3
    with pytest.raises(HTTPException) as error:
        await LifecycleService(db, "authentik_scim").synchronize(
            owner.authentik_sub, owner.username, owner.display_name, None, True
        )
    assert error.value.status_code == 409 and not owner.enabled
    await LifecycleService(db, str(admin.id)).configure(admin, admin.id, "fallback")
    await LifecycleService(db, "authentik_scim").synchronize(
        owner.authentik_sub, owner.username, owner.display_name, None, True
    )
    assert owner.enabled and scene[4].owner_user_id == admin.id
    assert not (await AuthorizationService().authorize(db, owner, "VIEW", scene[4].id)).allowed


async def test_no_new_direct_grant_to_disabled_subject(db, scene):
    from app.authorization.administration import ACLAdministrationService

    outsider = scene[1]
    await LifecycleService(db, "authentik_scim").synchronize(
        outsider.authentik_sub, outsider.username, outsider.display_name, None, False
    )
    service = ACLAdministrationService(db, scene[0], {})
    with pytest.raises(ValueError):
        await service.grant(scene[4].id, "USER", outsider.id, "VIEW", "ALLOW", True, False, "test")
    with pytest.raises(ValueError):
        await service.bind_role(scene[4].id, outsider.id, "READER")
    with pytest.raises(ValueError):
        await service.grant(
            scene[4].id, "USER", scene[0].id, "MANAGE_IDENTITY", "ALLOW", True, False, "test"
        )
