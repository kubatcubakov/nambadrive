from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.access_reviews.service import ReviewService, quarter_dates
from app.auth.dependencies import require_csrf
from app.authorization.service import AuthorizationService
from app.main import app
from app.models.access_review import AccessReview, AccessReviewItem
from app.models.acl import ACLEntry
from app.notifications.service import NotificationService
from tests.test_authorization import acl as make_acl
from tests.test_authorization import binding
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture

api, clean, scene, admin = api_fixture, clean_fixture, scene_fixture, admin_fixture


async def acl(*args, **kwargs):
    kwargs.setdefault("valid_from", datetime.now(UTC) - timedelta(days=1))
    return await make_acl(*args, **kwargs)


@pytest.fixture
async def review(db, scene, clean, admin):
    await acl(db, scene, resource=clean[0], subject=scene[1].id, permission="VIEW")
    await db.commit()
    await ReviewService(db, None, {}).create_due()
    return await db.scalar(select(AccessReview).where(AccessReview.resource_id == clean[0].id))


async def items(db, review):
    return (
        await db.scalars(select(AccessReviewItem).where(AccessReviewItem.review_id == review.id))
    ).all()


async def test_quarter_scheduler_is_idempotent_and_notifies_owners(db, scene, clean, admin, review):
    assert await ReviewService(db, None, {}).create_due() == 0
    assert len((await db.scalars(select(AccessReview))).all()) == 4
    await NotificationService(db).collect()
    assert any(row["kind"] == "REVIEW_DUE" for row in await NotificationService(db).list(scene[0]))
    assert not await NotificationService(db).list(admin)
    assert not await ReviewService(db, admin, {}).list()
    assert not await ReviewService(db, scene[1], {}).list()


async def test_review_api_owner_only_idor_and_csrf(api, db, scene, review, admin):
    client, state = api
    state["actor"] = admin
    assert (await client.get("/api/v1/access-reviews/" + str(review.id))).status_code == 403
    state["actor"] = scene[0]
    response = await client.get("/api/v1/access-reviews/" + str(review.id))
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    item = (await items(db, review))[0]
    path = f"/api/v1/access-reviews/{review.id}/items/{item.id}"
    assert (
        await client.post(path, json={"decision": "KEEP", "reason": "reviewed"})
    ).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    assert (
        await client.post(path, json={"decision": "KEEP", "reason": "reviewed"})
    ).status_code == 200
    assert (
        await client.post(path, json={"decision": "KEEP", "reason": "reviewed"})
    ).status_code == 409


async def test_revoke_is_immediate_central_acl_and_review_atomic(db, scene, clean, review):
    service = ReviewService(db, scene[0], {})
    item = next(row for row in await items(db, review) if row.snapshot["kind"] == "ACL")
    assert (await AuthorizationService().authorize(db, scene[1], "VIEW", clean[0].id)).allowed
    await service.decide(review.id, item.id, "REVOKE", "No longer needed")
    assert not (await AuthorizationService().authorize(db, scene[1], "VIEW", clean[0].id)).allowed
    for row in await items(db, review):
        if row.decision == "PENDING":
            await service.decide(review.id, row.id, "KEEP", "Owner validated")
    await service.complete(review.id)
    assert review.completed_at and review.completed_by == scene[0].id
    with pytest.raises(HTTPException):
        await service.refresh(review.id)


async def test_audit_failure_rolls_back_review_and_acl_revoke(db, scene, review):
    item = next(row for row in await items(db, review) if row.snapshot["kind"] == "ACL")
    with patch(
        "app.access_reviews.service.write_audit_event",
        new=AsyncMock(side_effect=OSError("disk full")),
    ):
        with pytest.raises(OSError):
            await ReviewService(db, scene[0], {}).decide(review.id, item.id, "REVOKE", "test")
    item_id = item.id
    await db.rollback()
    assert (await db.get(AccessReviewItem, item_id)).decision == "PENDING"
    assert (await db.scalar(select(ACLEntry))).revoked_at is None


async def test_new_grants_require_refresh_before_completion(db, scene, clean, review):
    service = ReviewService(db, scene[0], {})
    for row in await items(db, review):
        await service.decide(review.id, row.id, "KEEP", "test")
    await acl(db, scene, resource=clean[0], subject=scene[1].id, permission="DOWNLOAD")
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await service.complete(review.id)
    assert error.value.status_code == 409
    await service.refresh(review.id)
    pending = [row for row in await items(db, review) if row.decision == "PENDING"]
    assert len(pending) == 1 and pending[0].snapshot["permission_id"] == "DOWNLOAD"


async def test_changed_snapshot_cannot_be_approved(db, scene, review):
    item = next(row for row in await items(db, review) if row.snapshot["kind"] == "ACL")
    entry = await db.scalar(select(ACLEntry))
    entry.effect = "DENY"
    await db.commit()
    service = ReviewService(db, scene[0], {})
    with pytest.raises(HTTPException) as error:
        await service.decide(review.id, item.id, "KEEP", "test")
    assert error.value.status_code == 409
    await service.refresh(review.id)
    assert item.decision == "SUPERSEDED"
    assert any(
        row.decision == "PENDING" and row.snapshot.get("effect") == "DENY"
        for row in await items(db, review)
    )


async def test_overdue_review_never_revokes_rights(db, scene, clean, review):
    review.due_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    await ReviewService(db, None, {}).create_due()
    rows = await ReviewService(db, scene[0], {}).list()
    assert next(row for row in rows if row["id"] == review.id)["overdue"]
    assert (await AuthorizationService().authorize(db, scene[1], "VIEW", clean[0].id)).allowed
    assert (await db.scalar(select(ACLEntry))).revoked_at is None


async def test_inherited_grant_requires_authority_at_origin(db, scene, clean, review):
    from app.models.resource import Resource
    from tests.test_organization import user

    new_owner = await user(db)
    clean[0].owner_user_id = new_owner.id
    ancestor = scene[3]
    inherited = await acl(
        db,
        scene,
        resource=ancestor,
        subject=scene[1].id,
        permission="DOWNLOAD",
        propagate_to_children=True,
    )
    await db.commit()
    service = ReviewService(db, new_owner, {})
    await service.refresh(review.id)
    item = next(
        row
        for row in await items(db, review)
        if row.snapshot.get("origin") == str(ancestor.id) and row.snapshot["kind"] == "ACL"
    )
    with pytest.raises(HTTPException) as error:
        await service.decide(review.id, item.id, "REVOKE", "test")
    assert error.value.status_code == 403
    assert (await db.get(Resource, ancestor.id)).owner_user_id == scene[0].id
    assert inherited.revoked_at is None


async def test_system_grants_and_role_bindings_are_distinct(db, scene, clean, review):
    await binding(
        db,
        scene[1],
        "READER",
        resource_id=clean[0].id,
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    await db.commit()
    service = ReviewService(db, scene[0], {})
    await service.refresh(review.id)
    rows = await items(db, review)
    owner = next(row for row in rows if row.snapshot["kind"] == "OWNER")
    with pytest.raises(HTTPException):
        await service.decide(review.id, owner.id, "REVOKE", "test")
    role = next(row for row in rows if row.snapshot["kind"] == "ROLE")
    assert role.snapshot["permissions"] == ["PREVIEW", "VIEW"]
    await service.decide(review.id, role.id, "REVOKE", "test")
    assert role.decision == "REVOKE"


@pytest.mark.parametrize(
    "month,expected", [(1, (2026, 4)), (4, (2026, 7)), (9, (2026, 10)), (12, (2027, 1))]
)
def test_quarter_boundaries(month, expected):
    quarter, due = quarter_dates(datetime(2026, month, 15, tzinfo=UTC))
    assert quarter.month in {1, 4, 7, 10} and (due.year, due.month) == expected


async def test_postgres_concurrent_schedule_and_decision():
    import asyncio
    import os
    import uuid

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.organization import Company, Department
    from app.models.resource import Resource
    from app.models.user import User

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL review locks")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, cid, did, rid = [uuid.uuid4() for _ in range(4)]
    try:
        async with factory() as session:
            session.add_all(
                [
                    User(
                        id=uid, authentik_sub=str(uid), username="review-test", display_name="test"
                    ),
                    Company(id=cid, name=str(cid)),
                ]
            )
            await session.flush()
            session.add(Department(id=did, company_id=cid, name="test"))
            await session.flush()
            session.add(
                Resource(
                    id=rid, resource_type="SPACE", name="test", owner_user_id=uid, department_id=did
                )
            )
            await session.commit()

        async def create():
            async with factory() as session:
                return await ReviewService(session, None, {}).create_due()

        assert sum(await asyncio.gather(create(), create())) == 1
        async with factory() as session:
            review = await session.scalar(
                select(AccessReview).where(AccessReview.resource_id == rid)
            )
            item = await session.scalar(
                select(AccessReviewItem).where(AccessReviewItem.review_id == review.id)
            )
            review_id, item_id = review.id, item.id

        async def decide():
            async with factory() as session:
                actor = await session.get(User, uid)
                try:
                    await ReviewService(session, actor, {}).decide(
                        review_id, item_id, "KEEP", "reviewed"
                    )
                    return True
                except HTTPException as error:
                    assert error.status_code == 409
                    await session.rollback()
                    return False

        assert sum(await asyncio.gather(*(decide() for _ in range(5)))) == 1
    finally:
        async with factory() as session:
            await session.execute(
                delete(AccessReviewItem).where(
                    AccessReviewItem.review_id.in_(
                        select(AccessReview.id).where(AccessReview.resource_id == rid)
                    )
                )
            )
            await session.execute(delete(AccessReview).where(AccessReview.resource_id == rid))
            await session.execute(delete(Resource).where(Resource.id == rid))
            await session.execute(delete(Department).where(Department.id == did))
            await session.execute(delete(Company).where(Company.id == cid))
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
        await engine.dispose()
