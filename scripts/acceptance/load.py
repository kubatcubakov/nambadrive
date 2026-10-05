"""100 authenticated virtual users against real HTTP/PG; disposable metadata fixture only."""

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from app.auth.sessions import create_session
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models.organization import Company, Department
from app.models.resource import Resource
from app.models.user import User
from sqlalchemy import func, select
from sqlalchemy.engine import make_url


async def main():
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        os.environ.get("NAMBADRIVE_ACCEPTANCE_ISOLATED") != "1"
        or url.database != "nambadrive_acceptance"
        or url.get_backend_name() != "postgresql"
    ):
        raise RuntimeError("Dedicated disposable acceptance PostgreSQL required")
    target = "http://127.0.0.1:18778"
    actors, documents, cookies = [], [], []
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(User)):
            raise RuntimeError("Refuse to seed a populated database")
        operator = User(
            authentik_sub="fixture-operator",
            username="fixture-operator",
            display_name="Fixture operator",
        )
        db.add(operator)
        for i in range(100):
            user = User(
                authentik_sub=f"fixture-{i}",
                username=f"fixture-{i}",
                display_name="Load fixture",
            )
            actors.append(user)
            db.add(user)
        await db.flush()
        company = Company(name="Acceptance fixture")
        db.add(company)
        await db.flush()
        department = Department(company_id=company.id, name="Load fixture")
        db.add(department)
        await db.flush()
        space = Resource(
            resource_type="SPACE",
            name="Load fixture",
            owner_user_id=operator.id,
            department_id=department.id,
        )
        db.add(space)
        await db.flush()
        for actor in actors:
            folder = Resource(
                resource_type="FOLDER",
                name="Load fixture",
                parent_id=space.id,
                owner_user_id=actor.id,
                department_id=department.id,
            )
            db.add(folder)
            await db.flush()
            document = Resource(
                resource_type="DOCUMENT",
                name="Load fixture",
                parent_id=folder.id,
                owner_user_id=actor.id,
                department_id=department.id,
            )
            db.add(document)
            await db.flush()
            documents.append(document.id)
            cookies.append(
                await create_session(
                    db,
                    user=actor,
                    settings=settings,
                    ip="127.0.0.1",
                    user_agent="acceptance-load",
                )
            )
        await db.commit()
    latencies, results = [], {"authorized": 0, "denied": 0}
    started = time.perf_counter()

    async def virtual_user(index):
        # One cookie jar per actor; no auth dependency override or shared AsyncSession.
        async with httpx.AsyncClient(
            base_url=target,
            trust_env=False,
            timeout=30,
            cookies={settings.session_cookie_name: cookies[index]},
        ) as client:
            for _ in range(5):
                for identifier, expected in (
                    (documents[index], 200),
                    (documents[(index + 1) % 100], 403),
                ):
                    tick = time.perf_counter()
                    response = await client.get("/api/v1/resources/" + str(identifier))
                    latencies.append(time.perf_counter() - tick)
                    if response.status_code != expected:
                        raise RuntimeError(
                            "Authenticated load authorization contract failed"
                        )
                    if expected == 403 and str(identifier) in response.text:
                        raise RuntimeError("Cross-owner identifier leaked under load")
                    results["authorized" if expected == 200 else "denied"] += 1
                    if expected == 200 and response.json()["data"]["id"] != str(
                        identifier
                    ):
                        raise RuntimeError("Load response resource mismatch")
                    assert response.headers["Cache-Control"] == "no-store"

    try:
        await asyncio.gather(*(virtual_user(index) for index in range(100)))
        elapsed = time.perf_counter() - started
        ordered = sorted(latencies)
        p95 = ordered[int(len(ordered) * 0.95) - 1]
        # Engineering regression budget, not a production SLO or 500 GB capacity certificate.
        if p95 > 5 or elapsed > 180:
            raise RuntimeError("Acceptance metadata load regression budget exceeded")
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "virtual_users": 100,
            "requests": len(latencies),
            "authorized": results["authorized"],
            "expected_denials": results["denied"],
            "unexpected_results": 0,
            "p50_seconds": round(statistics.median(latencies), 4),
            "p95_seconds": round(p95, 4),
            "max_seconds": round(max(latencies), 4),
            "elapsed_seconds": round(elapsed, 4),
            "requests_per_second": round(len(latencies) / elapsed, 2),
            "scope": "real HTTP, server-side sessions, PostgreSQL, central ACL and durable denial audit",
            "production_500gb_capacity": "pending",
            "binary_upload_editor_load": "pending",
        }
        output = Path("acceptance-reports")
        output.mkdir(exist_ok=True)
        (output / "load.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
