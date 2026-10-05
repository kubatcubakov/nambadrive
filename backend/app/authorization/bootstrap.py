"""Trusted local operator command for the first administrator; no HTTP equivalent."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.audit.writer import write_audit_event
from app.authorization.catalog import role_id
from app.core.database import SessionLocal, engine
from app.models.acl import RoleBinding
from app.models.organization import OrganizationAdministrator
from app.models.user import User


async def bootstrap(user_id: uuid.UUID, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A bootstrap reason is required")
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # Serialize bootstrap across different target users on PostgreSQL.
                await db.execute(text("SELECT pg_advisory_xact_lock(735905)"))
                user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
                if user is None or not user.enabled:
                    raise ValueError("Mapped enabled Authentik user UUID required")
                if await db.scalar(select(OrganizationAdministrator)) is not None:
                    raise ValueError("First administrator already configured")
                db.add(OrganizationAdministrator(user_id=user_id))
                db.add(
                    RoleBinding(
                        user_id=user_id,
                        role_id=role_id("SYSTEM_ADMIN"),
                        resource_id=None,
                        valid_from=datetime.now(UTC),
                    )
                )
                await db.flush()
                await write_audit_event(
                    "change_acl",
                    user="local_operator",
                    resource=None,
                    correlation_id=str(uuid.uuid4()),
                    ip=None,
                    user_agent="bootstrap",
                    result="success",
                    reason=reason,
                    old_acl=None,
                    new_acl={
                        "user_id": str(user_id),
                        "role": "SYSTEM_ADMIN",
                        "organization_admin": True,
                    },
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=uuid.UUID, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    asyncio.run(bootstrap(args.user, args.reason))


if __name__ == "__main__":
    main()
