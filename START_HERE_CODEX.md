# Start here in Codex

Open this repository in Codex and use the following as the first task:

> Continue NambaDrive v1.0 from the current repository. Read `AGENTS.md` and all files under `docs/approved/` first. Treat them as approved requirements. Do not simplify security controls. Inspect current code before changing it. Current implementation includes Phases 0–4. Phase 4 local authorization regression tests are green. PostgreSQL 17 migration and authorization runtime validation passed; real Authentik validation remains pending; see docs/phase4-authorization.md. Phases 2–4 are implemented. Validate the authorization gate before continuing the approved sequence from Phase 5. For each phase create Alembic migrations, backend services/API, frontend minimum admin UI where appropriate, tests, documentation, and CI checks. Run available tests/lint/migrations after changes. Do not proceed past the ACL phase unless the authorization regression suite is green. Never expose PostgreSQL/Redis/OpenSearch/SeaweedFS directly to user network and never introduce direct browser-to-S3 access.

## Current first commands

```bash
find . -maxdepth 3 -type f | sort
cat AGENTS.md
cat README.md
cat docs/approved/requirements-v1.md
cat docs/approved/acl-model.md
```

For local AIO runtime:

```bash
cd deploy/aio
cp .env.example .env
# fill real DEV values

docker compose --env-file .env up -d --build
docker compose --env-file .env run --rm backend alembic upgrade head
```

If Docker or external Authentik is unavailable in the coding environment, continue implementation and automated unit/integration tests that do not require the external service; clearly report the unvalidated runtime boundary instead of weakening the implementation.
