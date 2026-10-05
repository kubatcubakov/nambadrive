# Phase 14 — quotas and durable allocation accounting

User, department (including descendants) and project limits are enforced before all new physical version writes: upload, ONLYOFFICE save, copy and version restoration. Usage includes pending, rejected, infected, old and trashed versions until successful governed physical purge. Data/quarantine duplicates of the same version are charged once. A missing limit is unlimited; zero blocks allocation. Lowering a limit below existing usage preserves content and blocks further allocation. Department moves and project assignments check the destination's already occupied usage. Projects are company-scoped; imported legacy project IDs remain disabled until administered.

The PostgreSQL hierarchy/governance advisory lock serializes allocation, hierarchy changes and cleanup. Before S3 I/O, a separate synchronous PostgreSQL transaction records the immutable version key, size, checksum, quota dimensions and policy scopes. Version metadata insertion and reservation removal commit together. A failed S3 write, audit or main transaction leaves a charged reservation: crashes cannot turn objects into unaccounted free space. A separate unpooled connection avoids exhaustion of the main request pool while lock waiters are active. SQLite is only a unit adapter; independent journal durability and competing final-byte allocations are tested on PostgreSQL.

Unknown reservations are exposed read-only to authorized administrators. There is no timer-based release or automatic orphan deletion. Reconciliation must establish object absence and quiesce writers before releasing accounting; existing unknown objects remain preserved until their governance provenance is resolved. Storage reservations and quota incidents are required backup metadata. Quota denials write durable audit and persist an incident for the Phase 15 notification worker even if the attempted document transaction rolls back.

## API and UI

`GET /api/v1/quotas/me` returns only the enabled caller's usage/limit. Global `MANAGE_QUOTAS` uses central AuthorizationService and SYSTEM_ADMIN binding; it grants no document access. Admin-only endpoints list/configure limits, inspect reservations and list/create projects. Project choices for a document require current EDIT permission and match its company. Mutations require CSRF; limit changes require a reason and fail closed on audit failure. The UI provides own usage, limit administration, company projects and reservation status. Document metadata editing includes project assignment.

## Validation

Tests cover admin/content separation, CSRF, parent department accounting, cross-company project rejection, copy/restore/Office limits, trash accounting, audit rollback, durable reservations after failed copy, and five concurrent uploads competing for one byte. Required phase gates include migration upgrade/schema check/downgrade/upgrade, all prior regression tests with authorization coverage >=90%, Ruff/mypy/Bandit/secret/dependency scans and frontend typecheck/lint/build. CI must be green before Phase 15.

Local results: 462 tests passed, 14 opt-in runtime skips; PostgreSQL 445 passed, one Redis opt-in skip (real Redis runs in CI). Authorization coverage 95.58% locally and 94.10% PostgreSQL. Migration roundtrip and all lint/type/security/frontend gates passed.
