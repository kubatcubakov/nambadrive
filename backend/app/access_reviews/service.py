from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import write_audit_event
from app.authorization.administration import ACLAdministrationService
from app.authorization.service import AuthorizationService, active, utc
from app.governance.policy import chain, governance_lock
from app.models.access_review import AccessReview, AccessReviewItem
from app.models.acl import ACLEntry, Role, RoleBinding, RolePermission
from app.models.organization import Department, DepartmentManager
from app.models.resource import Resource
from app.models.user import User


def quarter_dates(now: datetime) -> tuple[date, datetime]:
    month = ((now.month - 1) // 3) * 3 + 1
    quarter = date(now.year, month, 1)
    return quarter, datetime(
        now.year + (month == 10), 1 if month == 10 else month + 3, 1, tzinfo=UTC
    )


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def record(row: Any) -> dict[str, str]:
    return {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}


class ReviewService:
    def __init__(self, db: AsyncSession, actor: User | None, context: dict[str, Any]):
        self.db, self.actor, self.context = db, actor, context
        self.auth = AuthorizationService()

    async def permitted(self, resource_id: uuid.UUID) -> bool:
        return (
            self.actor is not None
            and (
                await self.auth.authorize_request_approval(self.db, self.actor, resource_id)
            ).allowed
        )

    async def require(self, resource_id: uuid.UUID) -> None:
        if not await self.permitted(resource_id):
            raise HTTPException(403, "Owner or department manager review required")

    async def snapshot(self, resource_id: uuid.UUID) -> dict[str, dict]:
        hierarchy = await chain(self.db, resource_id)
        for resource in reversed(hierarchy):
            await self.db.get(Resource, resource.id, with_for_update=True, populate_existing=True)
        scope = []
        for resource in hierarchy:
            scope.append(resource.id)
            if not resource.inherit_acl:
                break
        result: dict[str, dict] = {}
        for resource in hierarchy:
            result["OWNER:" + str(resource.id)] = dict(
                kind="OWNER",
                origin=str(resource.id),
                principal_type="USER",
                principal_id=str(resource.owner_user_id),
                permission="OWNER_SYSTEM_GRANT",
            )
        now = datetime.now(UTC)
        entries = (
            await self.db.scalars(
                select(ACLEntry)
                .where(ACLEntry.resource_id.in_(scope))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        for entry in entries:
            if active(entry, now) and (
                (entry.resource_id == resource_id)
                or (entry.resource_id != resource_id and entry.propagate_to_children)
            ):
                result["ACL:" + str(entry.id)] = dict(
                    kind="ACL", origin=str(entry.resource_id), **record(entry)
                )
        bindings = (
            await self.db.scalars(
                select(RoleBinding)
                .where(or_(RoleBinding.resource_id.in_(scope), RoleBinding.resource_id.is_(None)))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        for binding in bindings:
            if not active(binding, now):
                continue
            role = await self.db.get(Role, binding.role_id)
            permissions = sorted(
                (
                    await self.db.scalars(
                        select(RolePermission.permission_id).where(
                            RolePermission.role_id == binding.role_id
                        )
                    )
                ).all()
            )
            if not permissions and not any(
                value.get("kind") == "ACL"
                and value.get("principal_type") == "ROLE"
                and value.get("principal_id") == str(binding.role_id)
                for value in result.values()
            ):
                continue
            result["ROLE:" + str(binding.id)] = dict(
                kind="ROLE",
                origin=str(binding.resource_id) if binding.resource_id else None,
                role=role.name if role else "UNAVAILABLE",
                permissions=permissions,
                **record(binding),
            )
        department_ids = set()
        department_id: uuid.UUID | None = hierarchy[0].department_id
        while department_id is not None:
            if department_id in department_ids:
                raise ValueError("Invalid department hierarchy")
            department_ids.add(department_id)
            department = await self.db.get(Department, department_id, populate_existing=True)
            if department is None:
                raise ValueError("Department unavailable")
            department_id = department.parent_id
        managers = (
            await self.db.scalars(
                select(DepartmentManager)
                .where(DepartmentManager.department_id.in_(department_ids))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        for manager in managers:
            if active(manager, now):
                key = "MANAGER:" + str(manager.department_id) + ":" + str(manager.user_id)
                result[key] = dict(kind="MANAGER", origin=None, **record(manager))
        return result

    async def synchronize(self, review: AccessReview) -> None:
        current = await self.snapshot(review.resource_id)
        items = (
            await self.db.scalars(
                select(AccessReviewItem).where(AccessReviewItem.review_id == review.id)
            )
        ).all()
        known = {(item.source_key, item.fingerprint) for item in items}
        for item in items:
            if (
                item.decision == "SUPERSEDED"
                and item.source_key in current
                and fingerprint(current[item.source_key]) == item.fingerprint
            ):
                item.decision = "PENDING"
            if item.decision == "PENDING" and (
                item.source_key not in current
                or fingerprint(current[item.source_key]) != item.fingerprint
            ):
                item.decision = "SUPERSEDED"
        for key, snapshot in current.items():
            digest = fingerprint(snapshot)
            if (key, digest) not in known:
                self.db.add(
                    AccessReviewItem(
                        review_id=review.id, source_key=key, fingerprint=digest, snapshot=snapshot
                    )
                )
        await self.db.flush()

    async def create_due(self) -> int:
        await governance_lock(self.db)
        quarter, due = quarter_dates(datetime.now(UTC))
        resources = (
            await self.db.scalars(
                select(Resource)
                .where(
                    Resource.state == "ACTIVE",
                    Resource.purged_at.is_(None),
                    Resource.purge_started_at.is_(None),
                    ~select(AccessReview.id)
                    .where(AccessReview.resource_id == Resource.id, AccessReview.quarter == quarter)
                    .exists(),
                )
                .order_by(Resource.id)
                .limit(100)
            )
        ).all()
        for resource in resources:
            review = AccessReview(resource_id=resource.id, quarter=quarter, due_at=due)
            self.db.add(review)
            await self.db.flush()
            await self.synchronize(review)
            await write_audit_event(
                "access_review_created",
                resource=str(resource.id),
                review=str(review.id),
                result="success",
            )
        await self.db.commit()
        return len(resources)

    async def get(self, review_id: uuid.UUID, *, lock: bool = False) -> AccessReview:
        if lock:
            await governance_lock(self.db)
        review = await self.db.get(
            AccessReview, review_id, with_for_update=lock, populate_existing=True
        )
        if review is None:
            raise HTTPException(403, "Review unavailable")
        if lock:
            for resource in reversed(await chain(self.db, review.resource_id)):
                await self.db.get(
                    Resource, resource.id, with_for_update=True, populate_existing=True
                )
        await self.require(review.resource_id)
        return review

    async def list(self) -> list[dict]:
        if self.actor is None or not await self.auth.account_self(
            self.db, self.actor, self.actor.id
        ):
            raise HTTPException(403, "Review unavailable")
        reviews = (
            await self.db.scalars(
                select(AccessReview).order_by(AccessReview.quarter.desc(), AccessReview.id)
            )
        ).all()
        return [
            dict(
                id=row.id,
                resource_id=row.resource_id,
                quarter=row.quarter,
                due_at=row.due_at,
                completed_at=row.completed_at,
                overdue=row.completed_at is None and utc(row.due_at) < datetime.now(UTC),
            )
            for row in reviews
            if await self.permitted(row.resource_id)
        ]

    async def refresh(self, review_id: uuid.UUID) -> None:
        review = await self.get(review_id, lock=True)
        if review.completed_at:
            raise HTTPException(409, "Completed review is immutable")
        await self.synchronize(review)
        await self.audit("access_review_refreshed", review)
        await self.db.commit()

    async def decide(
        self, review_id: uuid.UUID, item_id: uuid.UUID, decision: str, reason: str
    ) -> None:
        review = await self.get(review_id, lock=True)
        item = await self.db.get(AccessReviewItem, item_id, with_for_update=True)
        if item is None or item.review_id != review.id:
            raise HTTPException(403, "Review item unavailable")
        if review.completed_at or item.decision != "PENDING":
            raise HTTPException(409, "Review item already decided")
        current = await self.snapshot(review.resource_id)
        if (
            item.source_key not in current
            or fingerprint(current[item.source_key]) != item.fingerprint
        ):
            raise HTTPException(409, "Grant changed; refresh the review")
        if decision not in {"KEEP", "REVOKE"} or not reason.strip():
            raise ValueError("Review decision and reason required")
        if decision == "REVOKE":
            origin = item.snapshot.get("origin")
            if not origin or item.snapshot["kind"] not in {"ACL", "ROLE"} or self.actor is None:
                raise HTTPException(
                    403, "System grants require their dedicated administration workflow"
                )
            admin = ACLAdministrationService(self.db, self.actor, self.context)
            if item.snapshot["kind"] == "ACL":
                await admin.revoke(uuid.UUID(origin), uuid.UUID(item.snapshot["id"]), commit=False)
            else:
                await admin.revoke_binding(
                    uuid.UUID(origin), uuid.UUID(item.snapshot["id"]), commit=False
                )
        item.decision, item.reason = decision, reason
        item.decided_by = self.actor.id if self.actor else None
        item.decided_at = datetime.now(UTC)
        await self.audit(
            "access_review_decision",
            review,
            item=str(item.id),
            decision=decision,
            reason=reason,
            snapshot=item.snapshot,
        )
        await self.db.commit()

    async def complete(self, review_id: uuid.UUID) -> None:
        review = await self.get(review_id, lock=True)
        if review.completed_at:
            raise HTTPException(409, "Review already complete")
        current = await self.snapshot(review.resource_id)
        items = (
            await self.db.scalars(
                select(AccessReviewItem).where(AccessReviewItem.review_id == review.id)
            )
        ).all()
        kept = {(item.source_key, item.fingerprint) for item in items if item.decision == "KEEP"}
        if any(item.decision == "PENDING" for item in items) or any(
            (key, fingerprint(snapshot)) not in kept for key, snapshot in current.items()
        ):
            raise HTTPException(409, "Review all current grants; refresh changed grants first")
        review.completed_at, review.completed_by = (
            datetime.now(UTC),
            self.actor.id if self.actor else None,
        )
        await self.audit("access_review_completed", review)
        await self.db.commit()

    async def audit(self, event: str, review: AccessReview, **details: Any) -> None:
        await write_audit_event(
            event,
            user=str(self.actor.id) if self.actor else None,
            resource=str(review.resource_id),
            review=str(review.id),
            result="success",
            **self.context,
            **details,
        )
