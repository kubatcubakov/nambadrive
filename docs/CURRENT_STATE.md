# Current repository state

Snapshot prepared for Codex handoff on 2026-10-05.

Implemented:
- Phase 0 foundation.
- Phase 1 Authentik OIDC implementation, opaque server-side sessions, CSRF, users/session migration, basic login UI, audit login/logout/login_failed, CI migration test.
- Phase 2 organization tables, services, administration API/UI and migration.
- Phase 3 unified security resource tree and PostgreSQL hierarchy validation.
- Phase 4 AuthorizationService, ACL/role bindings, scoped audited Break Glass and regression suite.

Validation: 272 local backend tests passed (96.43% authorization coverage); PostgreSQL 17.11 migration roundtrip and schema drift checks passed, with 257 authorization/API/trigger tests passing. See `implementation-validation.md` for exact boundaries.

Not yet implemented:
- upload/document operations (Phase 5 storage adapter is implemented)
- ClamAV/Tika/OpenSearch/ONLYOFFICE runtime stack
- sharing/access requests/retention/legal hold/quotas/notifications/access reviews

Real Authentik validation remains pending. Phase 5 storage adapter passed 282 local tests (two runtime-specific skips), 257 PostgreSQL tests, migration roundtrip/drift checks, Ruff, mypy, Bandit, secret scan, dependency audit and frontend gates. The separately run real SeaweedFS integration test passed. Phase 6 passed 312 local tests, 287 PostgreSQL tests and all lint/security/frontend gates. Real ClamAV 1.5.4 with official freshclam databases passed clean/EICAR tests. Phase 7 passed 330 local tests, 305 PostgreSQL tests, migration roundtrip/drift, Ruff/mypy/Bandit/secret/dependency checks and frontend gates. Phase 8 passed 336 local tests, 313 PostgreSQL tests including concurrency/immutability, migration roundtrip/drift and all lint/security/frontend gates. Phase 9 passed 353 local tests, 330 PostgreSQL tests, migration roundtrip/drift and lint/security/frontend gates. Live ONLYOFFICE browser runtime acceptance remains pending. Phases 10–22 remain pending. Trust code/tests and recorded validation rather than directory names.
