# Phase 16 — durable audit and Wazuh

Every JSONL record carries application/schema version, server-generated event ID and timestamp, user/resource (null when unknown/not applicable), IP, user agent, result and correlation ID. Request-scoped context is isolated across concurrent requests. Authenticated identity is filled by the server session dependency; worker events carry an explicit worker user agent and their own correlation ID. Known secret-bearing keys are recursively redacted; HTTP query strings, request bodies, cookies and authorization headers are not captured. User-supplied text is JSON-escaped. Schema envelope fields cannot be overridden by event payloads.

The writer uses append mode, no-follow opening, protected regular-file/ownership/link checks, cross-process advisory locking, complete write loops and fsync of both file and parent directory. Disk/write/fsync failure propagates; critical callers do not commit. A partial final record blocks subsequent operations until an operator preserves/rotates the segment. Concurrent-process tests include records larger than typical filesystem atomic write limits. There is no audit editing/deletion API. See the [collector and recovery runbook](../deploy/wazuh/README.md).

HTTP 401/403 responses generate an access_denied event with a normalized route template, not token-bearing raw URLs. Audit failure changes that response to a generic 503. Login now writes durable audit before committing the new application session. Existing critical paths preserve their audit-before-commit contract: ACL/roles, shares, retention/hold, managers and Break Glass. Explicit fsync-failure tests exercise actual writer propagation and rollback for ACL, manager, hold, retention and emergency grants. Ownership transfer auditing is implemented with its Phase 18 lifecycle; classification-edit UI/API remains part of Phase 19.

## Event map

| Events | Producer |
|---|---|
| login/logout/login_failed | OIDC and server-session routes |
| view/preview/download | Document endpoints, version history and ACL-filtered search |
| upload/edit | Upload/AV, metadata and signed Office sessions/save-as-version |
| rename/move/copy/delete/restore | Document/version service |
| share | Internal link generation and external share create/revoke/access |
| change_acl | ACL and scoped role administration (old/new snapshots) |
| access_request/access_approved/access_denied | Access workflow and denied HTTP requests |
| retention_changed/legal_hold_enabled/legal_hold_disabled | Governance service |
| quota_exceeded | Allocation accounting |
| malware_detected | Antivirus worker |
| admin_breakglass | Emergency grant issuance |
| print/download/clipboard_copy with office_capability_issued | Before signed editor capability issuance |

ONLYOFFICE signed sessions delegate permitted native editor actions for a bounded lifetime. Audit records explicitly describe capability issuance, including session UUID/expiry; they do **not** assert that a physical printer completed output. The official editor event API offers no reliable server confirmation of physical print. Capturing screens/printing already visible content is outside the approved v1 DRM scope. Live editor acceptance must check signed permission behavior; do not mistake a browser event or audit capability record for proof of a physical action. [Official ONLYOFFICE events](https://api.onlyoffice.com/docs/docs-api/usage-api/config/events/).

Audit entries before database commit record intent; if commit later fails, the entry remains as evidence. They are not distributed transactions or proof of commit. Critical audit failure prevents new state, while metadata/S3 cleanup intents provide recovery where physical storage is nontransactional. Log retention/agent delivery are external operational controls; app code does not delete old logs. No schema change is needed in Phase 16; the complete migration roundtrip remains a phase gate.

Validation: 500 local tests passed (15 opt-in skips), 484 PostgreSQL tests passed (one Redis opt-in skip); authorization coverage 95.77% / 94.40%. Full migration roundtrip/schema check, lint/types/security/dependencies and frontend gates pass. Wazuh engine gate runs in CI before Phase 17.
