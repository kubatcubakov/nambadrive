# AGENTS.md — NambaDrive engineering contract

This repository is NambaDrive v1.0, a secure corporate file server. Treat the documents under `docs/approved/` as approved requirements. Do not silently simplify them.

## Critical working rule
If a stronger coding/reasoning model is unavailable, do not intentionally downgrade architecture or security behavior. Stop at a safe checkpoint rather than replace an approved control with a weaker shortcut.

## Current code status
- Phase 0 Foundation: implemented.
- Phase 1 Authentik OIDC + server-side sessions + CSRF: implemented for DEV/UAT, not yet runtime-validated against the user's real Authentik.
- Phase 2 Organization structure: implemented, local gates green.
- Phase 3 Unified resource tree: implemented, local and PostgreSQL 17 gates green.
- Phase 4 Authorization/ACL engine: implemented with a green local authorization regression suite and >=90% coverage. PostgreSQL 17 runtime validation passed; real Authentik validation remains pending. See docs/phase4-authorization.md.
- Phase 5 immutable SeaweedFS adapter: implemented and runtime-tested against SeaweedFS 4.48. Phase 6 upload/ClamAV is implemented with quarantine, a durable scan queue and real ClamAV validation; document operations and later phases are pending.

Do not infer progress from directory names. Verify code.

## Approved technology choices
- Backend: Python 3.13 + FastAPI + SQLAlchemy async + Alembic.
- Frontend: React 19 + TypeScript + Vite.
- Identity: Authentik OIDC; MFA remains entirely in Authentik.
- Metadata: PostgreSQL 17.
- Queue/cache: Redis.
- Binary/object storage: on-prem SeaweedFS S3.
- Browser office editing: ONLYOFFICE Docs Community for Development/MVP.
- Search: Apache Tika + OpenSearch.
- AV: ClamAV.
- Audit: JSON Lines file -> Wazuh Agent.
- Deployment: Docker Compose with official profiles AIO, PROD-COMPACT, PROD-DISTRIBUTED.

## Security invariants — never weaken
1. Default DENY.
2. Ordinary ACL: DENY beats ALLOW.
3. Hard policy, retention, and Legal Hold cannot be bypassed by ordinary ACL.
4. System Administrator does not automatically read documents.
5. Department Manager receives full operational access to the department scope, but cannot override Legal Hold/Retention/hard security policy.
6. All authorization decisions go through one AuthorizationService. No scattered `if role == admin` authorization.
7. Frontend permissions are UX only and never trusted.
8. Browser never receives permanent S3 credentials or permanent S3 URLs.
9. OpenSearch never decides authorization; backend filters every result.
10. Each document version is immutable and stored as a separate S3 object.
11. Uploads are not ACTIVE until ClamAV succeeds.
12. Critical audit-controlled operations fail closed when durable audit cannot be written.
13. Legal Hold cannot be bypassed by Owner, Manager, System Admin, Break Glass, or cleanup worker.
14. Physical purge is not exposed to normal user API.
15. Raw session tokens, share tokens, secrets, OIDC tokens, and S3 credentials must never be logged.

## Core ACL model
Protected resources form one tree: SPACE -> FOLDER -> DOCUMENT. ACL entries attach to resources and principals USER / DEPARTMENT / ROLE. Resource owners and Department Managers are system grants, not ordinary ACL entries. `inherit_acl=false` stops inheritance above that resource.

Authorization evaluation order is approved as:
1. user validity
2. resource validity/state
3. hard security policy
4. retention/legal-hold constraints for the operation
5. valid Break Glass grant
6. ownership / ancestor owner / Department Manager grants
7. classification policy
8. explicit + inherited ACL (any applicable DENY wins)
9. role defaults/bindings
10. default DENY

Return an authorization decision object containing decision, reason, resource, source and permission. Every protected API must call AuthorizationService.

## Roles
SYSTEM_ADMIN, STORAGE_ADMIN, SECURITY_ADMIN(reserved v2), SPACE_OWNER, FOLDER_OWNER, DOCUMENT_OWNER, EDITOR, REVIEWER, READER, GUEST.

Default role intent:
- Editor: VIEW, PREVIEW, EDIT, UPLOAD_NEW_VERSION; no default DELETE/DOWNLOAD/SHARE/CHANGE_ACL.
- Reviewer: VIEW, PREVIEW, review/comments; no direct download/delete by default.
- Reader: VIEW, PREVIEW; DOWNLOAD separate.
- Guest: explicit permissions only.

## Document classifications
PUBLIC, INTERNAL, CONFIDENTIAL, STRICTLY_CONFIDENTIAL.
- anonymous external share only for PUBLIC.
- Confidential/Strictly Confidential external share hard denied.
- Strictly Confidential is hidden from request-access search without ACL and defaults DOWNLOAD/PRINT/CLIPBOARD/EXPORT_PDF off unless explicitly granted where policy allows.

## Versions / delete / retention
- Keep current + two previous versions normally.
- Soft delete -> Trash for 30 days.
- Physical purge only when trash period elapsed AND retention expired AND no Legal Hold.
- Retention is admin policy assignable to folder/type/space/document; contract example 5 years.
- Legal Hold always wins.

## Sharing
- Internal link requires Authentik + fresh ACL check.
- External anonymous share uses high-entropy token; DB stores only token hash.
- Default external expiration 7 days; maximum 30 days.
- Optional password, max views, allow view/download, revoke.
- Disable share links created by a disabled user.

## Identity lifecycle
Authentik `sub` is immutable external identity key; never use email as identity key. User may belong to multiple departments. Organization structure is maintained in NambaDrive UI. Each department can have multiple Department Managers. Manager gets full department operational access.

When user becomes disabled in Authentik: block new sessions, revoke NambaDrive sessions, revoke their external shares, deactivate their direct ACL subjects, transfer ownership Department Owner -> Space Owner -> Global Document Owner, audit everything.

## Storage rules
SeaweedFS object key is UUID based, e.g. `<space_uuid>/<document_uuid>/<version_uuid>`; never derive object key from filename/path. Backend/worker/ONLYOFFICE trusted flow can access storage, browser cannot. Compute SHA-256 per version.

## Search rules
Full text for DOCX/XLSX/PDF/TXT/CSV/JSON/XML via Tika -> OpenSearch. No OCR v1. Search returns only authorized docs. Request-access search may show only name/type/owner/department for inaccessible docs, never Strictly Confidential.

## Upload rules
Formats: DOCX/XLSX/PPTX/PDF/ZIP/JPG/PNG/DWG/PSD/TXT/CSV/JSON/XML. Default max size 500 MB configurable by admin. Upload -> quarantine -> ClamAV -> active. If ClamAV is unavailable, keep quarantined. ZIP bomb limits required.

## Audit/Wazuh
Audit is JSONL and application has no delete/edit feature for it. Required events include login/logout/login_failed/view/preview/download/upload/edit/rename/move/copy/delete/restore/share/print/change_acl/access_request/access_approved/access_denied/classification_changed/retention_changed/legal_hold_enabled/legal_hold_disabled/quota_exceeded/malware_detected/admin_breakglass. Include correlation_id, user, resource, IP, UA, result; ACL events include old/new ACL.

Critical fail-closed audit operations: ACL changes, external share creation/revoke, Legal Hold changes, Retention changes, Department Manager/ownership changes, Break Glass. If durable audit write fails, do not commit the operation.

## Deployment profiles
- AIO: one server + external backup; development/test/pilot/small production; no HA.
- PROD-COMPACT: preferred target for <=100 users / ~500 GB; app+ONLYOFFICE, data, two storage nodes, external backup.
- PROD-DISTRIBUTED: app, data, office, storage01, storage02, external backup.
Code/schema/API must be identical across profiles.

## Capacity baseline
<=100 users, ~500 GB initial logical data. Default file max 500 MB. For production storage plan for versions/replication/trash/retention; initial recommendation ~2 TB usable on each storage node.

## Development sequence
Do not skip phases:
0 Foundation [done]
1 Authentik identity [implemented, runtime validation pending]
2 organization structure
3 resource tree
4 ACL engine
5 SeaweedFS storage adapter
6 upload + ClamAV
7 documents and operations
8 versions
9 ONLYOFFICE
10 Tika/OpenSearch search
11 sharing
12 access requests
13 retention/legal hold
14 quotas
15 notifications
16 audit/Wazuh completion
17 access review
18 disabled-user lifecycle
19 admin dashboard
20 backup/restore
21 hardening
22 acceptance tests

Before document access is implemented, Phase 4 AuthorizationService and its regression test suite must be green.

## Testing gates
ACL/security changes require both positive and negative tests. Authorization module target coverage >=90%. Before merge: lint/typecheck/unit/ACL/security secret scan. Before release: integration tests, migration test, container scan, ZAP against test environment, backup restore test.

Never fail-open. DB/authz error -> deny/error, never allow.

## Current checkpoint
Phases 2–4 are implemented. See docs/phase2-organization.md, docs/phase3-resource-tree.md and docs/phase4-authorization.md for API contracts, validation and runtime boundaries. Phase 5 adapter is implemented; see docs/phase5-storage.md.

Before future document/storage work, rerun the Phase 4 authorization regression suite with >=90% coverage and validate the PostgreSQL 17 migrations/triggers in CI. All approved security invariants above remain binding. Do not infer runtime validation from generated SQL or SQLite tests.

Do not ask the user to re-answer already approved architecture questions unless a genuinely blocking contradiction is found.
