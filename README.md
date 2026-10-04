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

Full Authentik user lifecycle synchronization remains a later approved phase because it depends on objects not implemented yet.

## Start AIO

```bash
cd deploy/aio
cp .env.example .env
```

Edit `.env`, then:

```bash
docker compose --env-file .env up -d --build
docker compose --env-file .env run --rm backend alembic upgrade head
```

## Codex handoff

Read `AGENTS.md` and `START_HERE_CODEX.md` before continuing. Approved specifications are under `docs/approved/`.

## Next approved phase

Phase 2 — organizational structure.
