# Phase 13 — retention, Legal Hold and governed cleanup

Policy administration is separate from content access. Global MANAGE_RETENTION / MANAGE_LEGAL_HOLD decisions require an enabled SYSTEM_ADMIN binding through AuthorizationService, subject to global hard policy. Neither permission is an ordinary resource ACL/default role permission or Break Glass capability. Policy configuration returns IDs/settings/history, never document content or names to an otherwise unauthorized administrator.

## Retention and hold

Retention policies apply globally or to a document/folder/space subtree, optionally filtered by an approved filename format, for 1–36,500 days from each version's creation. The greatest applicable deadline wins. Every upload, Office callback, copy and version restoration materializes retention on the new immutable version; creating a policy also materializes existing versions. Copies/restores preserve source deadlines. Revoking a policy affects future versions only. PostgreSQL rejects clearing/shortening an already materialized version deadline. An explicit scope deadline can only be extended. A contracts folder can use a five-year policy (for example 1,826 days); no claim of jurisdiction-specific retention sufficiency is made.

Legal Hold is inherited regardless of ACL inheritance breaks and blocks every physical-cleanup path, including quarantine duplicates. Set/release requires reason, central administration authorization and durable audit. History is appended to legal_hold_events; no delete/edit endpoint exists. Releasing a hold does not erase history, undo other holds or shorten retained deadlines. Soft delete remains possible under retention/hold.

## API and UI

- `GET /api/v1/admin/governance/capabilities`: caller's administration capabilities.
- `GET|POST /api/v1/admin/governance/policies`: list/create scope/type policies; create requires name, days, reason, optional resource_id/document_type.
- `POST /api/v1/admin/governance/policies/{id}/revoke`: reason required, preserves history and existing version deadlines.
- `GET /api/v1/admin/governance/resources/{id}`: safe policy settings and hold history.
- `PUT .../resources/{id}/hold`: enabled + reason.
- `PUT .../resources/{id}/retention`: timezone-aware until + reason; extension only.

All mutations require CSRF. UI exposes policy scope/format/lifetime, future-policy revocation, scope extensions and hold history/set/release. Ordinary document owners/managers cannot release hold or change retention policy unless separately authorized as policy administrators.

## Worker and recovery

`python -m app.governance.worker` is an internal worker with storage credentials; there is no user physical-purge API. Every candidate uses AuthorizationService.authorize_cleanup. Hard PURGE policy, any ancestor Legal Hold and effective retention deny first. Then:

- Trashed documents require 30 elapsed days since soft delete.
- Obsolete clean versions require an elapsed 30-day version-trash interval, non-current status and at least three newer clean retained versions. An unexpired open ONLYOFFICE room pins its base version. Retention/hold preserves obsolete versions; after protection ends pruning is rescheduled conservatively.
- Infected/rejected content requires 30 days since scanning/rejection fallback creation.
- Extra quarantine copies of clean versions require 30 days since scan, no hold/retention, and full SHA/size verification of the separate data copy. Only the quarantine copy is deleted in this case.

The worker holds the same PostgreSQL advisory lock used by resource hierarchy mutation plus row locks during policy evaluation/deletion. Hold changes and moves cannot race past that critical section. Full purge first records an audited durable intent, commits it, reacquires locks and rechecks current policy. A hold accepted in between stops deletion. Purge intent prevents restoring partially deleted files after S3 failure. Before each physical attempt metadata constraints are flushed and an audit intent is fsynced. Deletions are idempotent across data/quarantine buckets; successful completion is audited and marks tombstone timestamps. Resource/version/ACL/share/Office history remains in PostgreSQL. If S3/audit/commit fails, retry metadata and audit intents permit reconciliation without pretending storage is transactional. A later hold preserves any remaining copies; it cannot restore bytes legitimately deleted before that hold was accepted.

No response to an ordinary user serves a purging/purged document. Quarantine-copy deletion never removes the verified data version. Retry after dependency failure is five minutes; ineligible candidates are revisited after six hours to avoid starving other work. Unknown/orphan storage keys are not automatically deleted: without trustworthy policy provenance the worker fails closed. Storage inventory/reconciliation remains an operational task, not a permissive orphan-deletion shortcut.

## Validation

Tests cover policy-scope/type matching, monotonic bound deadlines, audit rollback, system-admin-without-content-access, CSRF, inherited hold, quarantine retention, verified duplicate cleanup, partial deletion/retry/no restore, current+2 pruning, editor pins and malformed hierarchy. PostgreSQL tests exercise the retention trigger and a committed hold blocking an already waiting cleanup transaction. Validation: 443 local tests, 424 PostgreSQL tests, authorization coverage 95.74% locally / 94.35% PostgreSQL service. Per-phase gates include migration roundtrip/schema drift, complete authorization regression with >=90% coverage, frontend build/lint/types, backend Ruff/mypy/Bandit, secrets and dependency audit. These checks do not constitute full production storage/backup/restore acceptance (Phases 20–22).
