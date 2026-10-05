import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.authorization.administration import ACLAdministrationService
from app.authorization.catalog import DEFAULTS, PERMISSIONS, ROLES, role_id
from app.authorization.service import AuthorizationService
from app.departments.service import OrganizationService
from app.models.acl import (
    ACLEntry,
    BreakGlassGrant,
    HardPolicy,
    Permission,
    Role,
    RoleBinding,
    RolePermission,
)
from app.models.organization import Company, Department, DepartmentManager, DepartmentMembership
from app.resources.service import ResourceService
from tests.test_organization import user

NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def scene(db):
    owner, outsider = await user(db), await user(db)
    db.add_all(
        [Permission(id=p) for p in PERMISSIONS] + [Role(id=role_id(r), name=r) for r in ROLES]
    )
    await db.flush()
    db.add_all(
        [
            RolePermission(role_id=role_id(r), permission_id=p)
            for r, ps in DEFAULTS.items()
            for p in ps
        ]
    )
    await db.commit()
    with (
        patch("app.departments.service.write_audit_event", new=AsyncMock()),
        patch("app.resources.service.write_audit_event", new=AsyncMock()),
    ):
        org = OrganizationService(db, owner, {})
        company = await org.create_company("Company")
        dept = await org.create_department(company.id, "Department", None)
        child = await org.create_department(company.id, "Section", dept.id)
        svc = ResourceService(db, owner, {})
        space = await svc.create("SPACE", "Space", dept.id)
        folder = await svc.create("FOLDER", "Folder", child.id, space.id)
        doc = await svc.create("DOCUMENT", "Document", child.id, folder.id)
    return owner, outsider, space, folder, doc, dept, child


async def acl(
    db,
    scene,
    *,
    resource=None,
    subject=None,
    principal_type="USER",
    permission="VIEW",
    effect="ALLOW",
    **kw,
):
    owner, outsider, _, _, doc, _, _ = scene
    row = ACLEntry(
        resource_id=(resource or doc).id,
        principal_type=principal_type,
        principal_id=subject or outsider.id,
        permission_id=permission,
        effect=effect,
        applies_to_self=True,
        propagate_to_children=False,
        valid_from=NOW - timedelta(days=1),
        valid_until=None,
        revoked_at=None,
        created_by=owner.id,
        reason="test",
        **{},
    )
    for key, value in kw.items():
        setattr(row, key, value)
    db.add(row)
    await db.commit()
    return row


async def binding(db, subject, name, resource=None, **kw):
    row = RoleBinding(
        user_id=subject.id,
        role_id=role_id(name),
        resource_id=resource.id if resource else None,
        valid_from=NOW - timedelta(days=1),
        valid_until=None,
        revoked_at=None,
    )
    for key, value in kw.items():
        setattr(row, key, value)
    db.add(row)
    await db.commit()
    return row


async def authorize(db, actor, resource, permission="VIEW", **kw):
    return await AuthorizationService().authorize(
        db, actor, permission, resource.id if resource else None, now=NOW, **kw
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("permission", sorted(PERMISSIONS - {"CREATE_SPACE", "PURGE"}))
async def test_role_default_matrix(db, scene, role, permission):
    _, actor, space, _, doc, _, _ = scene
    await binding(db, actor, role, space)
    result = await authorize(db, actor, doc, permission)
    assert result.allowed == (permission in DEFAULTS.get(role, set()))


async def test_default_unknown_missing_disabled_session(db, scene):
    owner, outsider, _, _, doc, _, _ = scene
    assert (await authorize(db, outsider, doc)).reason == "DEFAULT_DENY"
    assert (await authorize(db, owner, doc, "UNKNOWN")).reason == "UNKNOWN_PERMISSION"
    assert (await authorize(db, owner, None)).reason == "RESOURCE_INVALID"
    assert (await authorize(db, owner, doc, session_valid=False)).reason == "USER_INVALID"
    assert (
        await AuthorizationService().authorize(db, owner, "VIEW", uuid.uuid4())
    ).reason == "RESOURCE_INVALID"
    missing = type(owner)(id=uuid.uuid4(), enabled=True)
    assert (await authorize(db, missing, doc)).reason == "USER_INVALID"
    owner.enabled = False
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "USER_INVALID"


@pytest.mark.parametrize("scope", ["document", "ancestor"])
async def test_owner_system_grant_precedes_ordinary_deny(db, scene, scope):
    owner, outsider, space, folder, doc, _, _ = scene
    if scope == "ancestor":
        doc.owner_user_id, folder.owner_user_id = outsider.id, outsider.id
    await acl(db, scene, subject=owner.id, effect="DENY")
    result = await authorize(db, owner, doc)
    assert result.allowed and result.reason == "OWNER"
    assert result.source_resource_id == (doc.id if scope == "document" else space.id)


async def test_deny_beats_allow_across_principals(db, scene):
    _, actor, space, _, doc, dept, _ = scene
    db.add(DepartmentMembership(user_id=actor.id, department_id=dept.id, kind="PRIMARY"))
    await binding(db, actor, "READER", space)
    await acl(db, scene)
    deny = await acl(
        db,
        scene,
        resource=space,
        principal_type="DEPARTMENT",
        subject=dept.id,
        effect="DENY",
        propagate_to_children=True,
    )
    result = await authorize(db, actor, doc)
    assert result.reason == "ACL_DENY" and result.source_resource_id == space.id
    deny.revoked_at = NOW
    await db.commit()
    assert (await authorize(db, actor, doc)).reason == "ACL_ALLOW"
    await acl(db, scene, principal_type="ROLE", subject=role_id("READER"), effect="DENY")
    assert not (await authorize(db, actor, doc)).allowed


@pytest.mark.parametrize(
    "propagate,self_only,allow", [(False, True, False), (True, False, True), (True, True, True)]
)
async def test_inheritance_propagation_and_stop(db, scene, propagate, self_only, allow):
    _, actor, space, folder, doc, _, _ = scene
    await acl(db, scene, resource=space, applies_to_self=self_only, propagate_to_children=propagate)
    assert (await authorize(db, actor, doc)).allowed == allow
    folder.inherit_acl = False
    await db.commit()
    assert not (await authorize(db, actor, doc)).allowed
    await acl(db, scene, resource=folder, propagate_to_children=True)
    assert (await authorize(db, actor, doc)).allowed
    doc.inherit_acl = False
    await db.commit()
    assert not (await authorize(db, actor, doc)).allowed
    await acl(db, scene)
    assert (await authorize(db, actor, doc)).allowed


@pytest.mark.parametrize(
    "field,value",
    [("valid_from", NOW + timedelta(seconds=1)), ("valid_until", NOW), ("revoked_at", NOW)],
)
async def test_temporary_acl_and_binding(db, scene, field, value):
    _, actor, space, _, doc, _, _ = scene
    await acl(db, scene, **{field: value})
    await binding(db, actor, "READER", space, **{field: value})
    assert not (await authorize(db, actor, doc)).allowed


async def test_manager_scope_expiry_revocation_and_membership_disabled(db, scene):
    owner, actor, space, _, doc, dept, child = scene
    manager = DepartmentManager(
        user_id=actor.id,
        department_id=dept.id,
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
    )
    db.add(manager)
    await acl(db, scene, effect="DENY")
    assert (await authorize(db, actor, doc)).reason == "DEPARTMENT_MANAGER"
    manager.valid_until = NOW
    await db.commit()
    assert (await authorize(db, actor, doc)).reason == "ACL_DENY"
    manager.valid_until, manager.revoked_at = None, NOW
    await db.commit()
    assert not (await authorize(db, actor, doc)).allowed
    manager.revoked_at = None
    sibling = Department(company_id=dept.company_id, name="Sibling")
    db.add(sibling)
    await db.flush()
    doc.department_id = sibling.id
    await db.commit()
    assert not (await authorize(db, actor, doc)).allowed
    doc.department_id = child.id
    db.add(HardPolicy(resource_id=space.id, permission_id="VIEW", reason="security"))
    await db.commit()
    assert (await authorize(db, actor, doc)).reason == "HARD_POLICY"


@pytest.mark.parametrize("kind", ["QUARANTINED", "TRASH"])
async def test_resource_and_ancestor_state_precedes_owner(db, scene, kind):
    owner, _, _, folder, doc, _, _ = scene
    folder.state = kind
    folder.deleted_at = NOW if kind == "TRASH" else None
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "RESOURCE_STATE"


@pytest.mark.parametrize("target", ["company", "department"])
async def test_disabled_organization_precedes_grants(db, scene, target):
    owner, _, _, _, doc, _, child = scene
    row = await db.get(Company, child.company_id) if target == "company" else child
    row.enabled = False
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "ORGANIZATION_DISABLED"


async def test_inheritance_break_does_not_stop_hard_policy_or_ownership(db, scene):
    owner, actor, space, folder, doc, _, _ = scene
    folder.inherit_acl = False
    doc.owner_user_id, folder.owner_user_id = actor.id, actor.id
    await db.commit()
    assert (await authorize(db, owner, doc)).allowed
    await binding(db, actor, "READER", space)
    await acl(db, scene, resource=space, propagate_to_children=True)
    db.add(HardPolicy(resource_id=space.id, permission_id="VIEW", reason="hard deny"))
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "HARD_POLICY"


@pytest.mark.parametrize("classification", ["INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"])
async def test_external_share_hard_policy(db, scene, classification):
    owner, _, _, _, doc, _, _ = scene
    doc.classification = classification
    await db.commit()
    assert (
        await authorize(db, owner, doc, "EXTERNAL_SHARE")
    ).reason == "CLASSIFICATION_HARD_POLICY"


async def test_strict_classification_explicit_controls(db, scene):
    _, actor, space, _, doc, _, _ = scene
    doc.classification = "STRICTLY_CONFIDENTIAL"
    await binding(db, actor, "READER", space)
    assert (await authorize(db, actor, doc)).allowed
    for permission in (
        "DOWNLOAD",
        "PRINT",
        "CLIPBOARD_COPY",
        "EXPORT_PDF",
        "REQUEST_ACCESS_DISCOVERY",
    ):
        assert (
            await authorize(db, actor, doc, permission)
        ).reason == "CLASSIFICATION_REQUIRES_EXPLICIT_GRANT"
    await acl(db, scene, permission="DOWNLOAD")
    assert (await authorize(db, actor, doc, "DOWNLOAD")).reason == "ACL_ALLOW"
    await acl(db, scene, permission="DOWNLOAD", effect="DENY")
    assert (await authorize(db, actor, doc, "DOWNLOAD")).reason == "ACL_DENY"


async def emergency(db, actor, resource, permission="VIEW", **kw):
    grant = BreakGlassGrant(
        user_id=actor.id,
        resource_id=resource.id,
        permission_id=permission,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=30),
        reason="incident",
        created_by=actor.id,
        audited=True,
    )
    for k, v in kw.items():
        setattr(grant, k, v)
    db.add(grant)
    await db.commit()
    return grant


async def test_break_glass_scoped_audited_and_hard_denied(db, scene):
    _, actor, space, _, doc, _, _ = scene
    await acl(db, scene, effect="DENY")
    await emergency(db, actor, space)
    assert (await authorize(db, actor, doc)).reason == "BREAK_GLASS"
    db.add(HardPolicy(resource_id=None, permission_id="VIEW", reason="global"))
    await db.commit()
    assert (await authorize(db, actor, doc)).reason == "HARD_POLICY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("audited", False),
        ("reason", " "),
        ("valid_until", NOW),
        ("revoked_at", NOW),
        ("valid_from", NOW + timedelta(seconds=1)),
        ("valid_until", NOW + timedelta(hours=2)),
    ],
)
async def test_invalid_break_glass_denied(db, scene, field, value):
    _, actor, space, _, doc, _, _ = scene
    if (
        os.environ.get("NAMBADRIVE_TEST_POSTGRES") == "1"
        and field == "valid_until"
        and value > NOW + timedelta(hours=1)
    ):
        with pytest.raises(IntegrityError, match="break_glass_max_hour"):
            await emergency(db, actor, space, **{field: value})
        await db.rollback()
        return
    await emergency(db, actor, space, **{field: value})
    assert not (await authorize(db, actor, doc)).allowed


@pytest.mark.parametrize("constraint", ["hold", "retention", "trash"])
async def test_purge_owner_manager_admin_and_breakglass_cannot_bypass(db, scene, constraint):
    owner, actor, space, _, doc, dept, _ = scene
    doc.state, doc.deleted_at = "TRASH", NOW - timedelta(days=31)
    if constraint == "hold":
        space.legal_hold = True
    elif constraint == "retention":
        space.retention_until = NOW + timedelta(days=1)
    else:
        doc.deleted_at = NOW - timedelta(days=29)
    db.add(
        DepartmentManager(
            user_id=actor.id, department_id=dept.id, valid_from=NOW - timedelta(days=1)
        )
    )
    await binding(db, actor, "SYSTEM_ADMIN")
    await emergency(db, actor, space, "PURGE")
    expected = {"hold": "LEGAL_HOLD", "retention": "RETENTION", "trash": "TRASH_PERIOD"}[constraint]
    assert (await authorize(db, owner, doc, "PURGE")).reason == expected
    assert (await authorize(db, actor, doc, "PURGE")).reason == expected


async def test_purge_policy_allows_after_constraints_and_soft_delete_hold(db, scene):
    owner, _, _, _, doc, _, _ = scene
    doc.legal_hold = True
    await db.commit()
    assert (await authorize(db, owner, doc, "DELETE")).allowed
    doc.legal_hold, doc.state, doc.deleted_at = False, "TRASH", NOW - timedelta(days=31)
    await db.commit()
    assert (await authorize(db, owner, doc, "PURGE")).allowed


async def test_system_admin_configuration_not_content(db, scene):
    _, actor, _, _, doc, _, _ = scene
    assert not (await authorize(db, actor, None, "CREATE_SPACE")).allowed
    await binding(db, actor, "SYSTEM_ADMIN")
    assert (await authorize(db, actor, None, "CREATE_SPACE")).allowed
    assert not (await authorize(db, actor, doc)).allowed
    assert not (await authorize(db, actor, doc, "CREATE_SPACE")).allowed


async def test_acl_admin_grant_revoke_idor_and_audit_failure(db, scene):
    owner, actor, _, folder, doc, _, _ = scene
    svc = ACLAdministrationService(db, owner, {})
    with patch("app.authorization.administration.write_audit_event", new=AsyncMock()) as audit:
        entry = await svc.grant(doc.id, "USER", actor.id, "VIEW", "ALLOW", True, False, "review")
        assert entry in await svc.list_entries(doc.id)
        with pytest.raises(HTTPException):
            await svc.revoke(folder.id, entry.id)
        await svc.revoke(doc.id, entry.id)
        assert entry.revoked_at
        assert audit.await_count == 2
    uid, rid = actor.id, doc.id
    with patch(
        "app.authorization.administration.write_audit_event", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            await svc.grant(rid, "USER", uid, "DOWNLOAD", "ALLOW", True, False, "test")
    await db.rollback()
    assert not (
        await db.scalars(select(ACLEntry).where(ACLEntry.permission_id == "DOWNLOAD"))
    ).all()


@pytest.mark.parametrize(
    "bad", ["principal", "missing", "disabled", "permission", "effect", "reason", "scope", "dates"]
)
async def test_invalid_acl_admin_inputs(db, scene, bad):
    owner, actor, _, _, doc, _, _ = scene
    args = dict(
        resource_id=doc.id,
        principal_type="USER",
        principal_id=actor.id,
        permission="VIEW",
        effect="ALLOW",
        applies_to_self=True,
        propagate_to_children=False,
        reason="test",
    )
    if bad == "principal":
        args["principal_type"] = "INVALID"
    if bad == "missing":
        args["principal_id"] = uuid.uuid4()
    if bad == "disabled":
        actor.enabled = False
        await db.commit()
    if bad == "permission":
        args["permission"] = "PURGE"
    if bad == "effect":
        args["effect"] = "INVALID"
    if bad == "reason":
        args["reason"] = " "
    if bad == "scope":
        args["applies_to_self"] = False
    if bad == "dates":
        args.update(valid_from=NOW, valid_until=NOW)
    with pytest.raises(ValueError):
        await ACLAdministrationService(db, owner, {}).grant(**args)


async def test_unprivileged_acl_and_emergency_denied(db, scene):
    _, actor, _, _, doc, _, _ = scene
    svc = ACLAdministrationService(db, actor, {})
    with pytest.raises(HTTPException):
        await svc.list_entries(doc.id)
    with pytest.raises(HTTPException):
        await svc.break_glass(doc.id, "VIEW", "incident", 30)


async def test_emergency_creation_audit_failure_and_expiry_cap(db, scene):
    _, actor, _, _, doc, _, _ = scene
    await binding(db, actor, "SYSTEM_ADMIN", valid_from=datetime.now(UTC) - timedelta(days=1))
    svc = ACLAdministrationService(db, actor, {})
    with patch("app.authorization.administration.write_audit_event", new=AsyncMock()):
        grant = await svc.break_glass(doc.id, "VIEW", "incident", 60)
        assert grant.valid_until - grant.valid_from == timedelta(hours=1)
        for permission, reason, minutes in [
            ("PURGE", "incident", 30),
            ("VIEW", " ", 30),
            ("VIEW", "incident", 61),
        ]:
            with pytest.raises(ValueError):
                await svc.break_glass(doc.id, permission, reason, minutes)
    with patch(
        "app.authorization.administration.write_audit_event", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            await svc.break_glass(doc.id, "DOWNLOAD", "incident", 5)
    await db.rollback()
    assert not (
        await db.scalars(select(BreakGlassGrant).where(BreakGlassGrant.permission_id == "DOWNLOAD"))
    ).all()


async def test_database_error_does_not_allow(db, scene):
    owner, _, _, _, doc, _, _ = scene
    with patch.object(db, "scalar", side_effect=RuntimeError("database down")):
        with pytest.raises(RuntimeError):
            await authorize(db, owner, doc)


async def test_scoped_role_binding_audited_and_revoked(db, scene):
    owner, actor, _, folder, doc, _, _ = scene
    svc = ACLAdministrationService(db, owner, {})
    with patch("app.authorization.administration.write_audit_event", new=AsyncMock()) as audit:
        row = await svc.bind_role(folder.id, actor.id, "EDITOR")
        result = await AuthorizationService().authorize(db, actor, "EDIT", doc.id)
        assert result.allowed
        await svc.revoke_binding(folder.id, row.id)
        assert not (await AuthorizationService().authorize(db, actor, "EDIT", doc.id)).allowed
        assert audit.await_count == 2
        with pytest.raises(HTTPException):
            await svc.revoke_binding(doc.id, row.id)
    for role in ("SYSTEM_ADMIN", "SECURITY_ADMIN", "INVALID"):
        with pytest.raises(ValueError):
            await svc.bind_role(doc.id, actor.id, role)
    with pytest.raises(ValueError):
        await svc.bind_role(doc.id, actor.id, "READER", datetime.now(UTC) - timedelta(seconds=1))
    actor.enabled = False
    await db.commit()
    with pytest.raises(ValueError):
        await svc.bind_role(doc.id, actor.id, "READER")


async def test_binding_audit_failure_rolls_back(db, scene):
    owner, actor, _, _, doc, _, _ = scene
    with patch(
        "app.authorization.administration.write_audit_event", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            await ACLAdministrationService(db, owner, {}).bind_role(doc.id, actor.id, "READER")
    await db.rollback()
    assert not (await db.scalars(select(RoleBinding))).all()


async def test_global_policy_precedes_admin_configuration(db, scene):
    _, actor, _, _, _, _, _ = scene
    await binding(db, actor, "SYSTEM_ADMIN")
    db.add(HardPolicy(resource_id=None, permission_id="CREATE_SPACE", reason="maintenance"))
    await db.commit()
    assert (await authorize(db, actor, None, "CREATE_SPACE")).reason == "HARD_POLICY"


async def test_disabled_department_ancestor_denies_even_owner(db, scene):
    owner, _, _, _, doc, dept, _ = scene
    dept.enabled = False
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "ORGANIZATION_DISABLED"


async def test_department_cycle_fails_closed(db, scene):
    owner, _, _, _, doc, dept, child = scene
    dept.parent_id = child.id
    await db.commit()
    assert (await authorize(db, owner, doc)).reason == "ORGANIZATION_INVALID"


async def test_department_subject_no_grant_when_disabled(db, scene):
    _, actor, _, _, doc, dept, _ = scene
    other_company = Company(name="Other")
    db.add(other_company)
    await db.flush()
    other_dept = Department(name="Other dept", company_id=other_company.id)
    db.add(other_dept)
    await db.flush()
    db.add(DepartmentMembership(user_id=actor.id, department_id=other_dept.id, kind="SECONDARY"))
    await acl(db, scene, principal_type="DEPARTMENT", subject=other_dept.id)
    assert (await authorize(db, actor, doc)).allowed
    other_company.enabled = False
    await db.commit()
    assert not (await authorize(db, actor, doc)).allowed
