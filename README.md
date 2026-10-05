# NambaDrive

Secure corporate file server — implementation repository.

## Current implementation status

**Phase 0 — Foundation: complete**

- FastAPI backend
- React/TypeScript frontend
- PostgreSQL
- Redis
- Alembic
- Nginx AIO reverse proxy
- `/api/v1/health/live`
- `/api/v1/health/ready`

**Phase 1 — Authentik Identity: implemented for DEV/UAT**

- Authentik OIDC Authorization Code flow
- PKCE S256
- state + nonce validation
- discovery issuer validation
- JWKS/ID-token signature validation
- audience/issuer/exp/iat/sub/nonce validation
- immutable `sub` user mapping
- users table
- server-side application sessions
- raw session token never stored in PostgreSQL
- HttpOnly application-session cookie
- CSRF token for state-changing API requests
- `/api/v1/auth/login`
- `/api/v1/auth/callback`
- `/api/v1/auth/me`
- `/api/v1/auth/csrf`
- `/api/v1/auth/logout`
- login/logout/login_failed JSON audit events
- basic frontend login/logout/profile state

Full Authentik user lifecycle synchronization (periodic detection of disabled users, ownership transfer, share revocation) remains a later approved phase because it depends on objects not implemented yet.

## Start AIO

```bash
cd deploy/aio
cp .env.example .env
```

Edit `.env`. At minimum set:

- `POSTGRES_PASSWORD`
- `NAMBADRIVE_DATABASE_URL` with the same DB password
- `NAMBADRIVE_PUBLIC_URL`
- Authentik issuer/discovery/client ID/client secret
- long random `NAMBADRIVE_CSRF_SECRET`

Then:

```bash
docker compose --env-file .env up -d --build

docker compose --env-file .env run --rm backend alembic upgrade head
```

Health:

```bash
curl http://localhost:8080/api/v1/health/live
curl http://localhost:8080/api/v1/health/ready
```

Open:

```text
http://localhost:8080
```

## Authentik

See `docs/authentik.md`.

## Important security boundary

NambaDrive does not persist Authentik OIDC tokens in browser storage. After successful OIDC authentication, the application issues its own opaque server-side session. Only the SHA-256 hash of that session token is persisted in PostgreSQL.

## Codex handoff

Read `AGENTS.md` and `START_HERE_CODEX.md` before continuing. Approved specifications are under `docs/approved/`.

## Organization, resources and authorization

Phases 2–4 are implemented: company/department hierarchy, membership and managers, a unified security resource tree, and centralized AuthorizationService with audited ACL/role administration and scoped Break Glass. The frontend includes minimum organization and resource administration.

Validation includes SQLite and PostgreSQL 17 migrations, schema drift checks, ACL/API regressions, >=90% authorization coverage, lint/typechecks and dependency/security scans. Real Authentik deployment validation remains pending. See [the validation report](docs/implementation-validation.md).

The next approved phase is Phase 5, the SeaweedFS storage adapter. Document content operations must preserve the authorization gate and all approved controls.
