# Phase 12 — access requests and temporary ACL grants

Users request exactly VIEW, EDIT or DOWNLOAD, with a reason and optional timezone-aware expiry. One current resource/ancestor owner or Department Manager may approve or deny. Approval is a normal direct-user ALLOW ACL, not an exceptional grant; ordinary DENY, hard policy, classification, resource state and user validity continue to apply. Approval never silently grants other permissions: VIEW exposes document information, PREVIEW and other content actions retain their separate authorization requirements. The approver may shorten the requested expiry; extending it requires a new explicit ACL administration action. An already expired request cannot be approved.

## Discovery and authorization

`GET /api/v1/access-requests/discovery?q=...&limit=20` is filename-only search. It returns only document ID (needed to address a request), name, type, owner ID and department ID. No body text, snippets, version/content metadata, total counts or scores. Every row passes central `authorize_discovery`; Strictly Confidential anywhere in its ancestor chain is always hidden from this request-discovery endpoint. A user who already has VIEW can still request another permission on that known document.

Discovery follows default DENY. Owners/Managers have their approved system scope; other users need an explicit REQUEST_ACCESS_DISCOVERY ACL, normally granted to a department at a space/folder with propagation. Nothing adds discovery to Reader/Editor defaults or enables global cross-company browsing. This is a metadata capability, never VIEW/PREVIEW/DOWNLOAD. Ordinary DENY wins. Owners configure it with the existing ACL administration UI.

Request creation requires either current VIEW or allowed discovery, and an ACTIVE document in an enabled hierarchy. Mine/inbox lists are filtered using fresh central decisions. Only a current owner/ancestor owner or manager with CHANGE_ACL may decide; a user holding a delegated CHANGE_ACL entry, SYSTEM_ADMIN label or Break Glass does not become a request approver. Recipients are the shared owner/manager inbox; notification delivery is Phase 15.

## API and UI

- `POST /api/v1/access-requests`: resource_id, permission, reason, optional valid_until. Authenticated, CSRF-protected.
- `GET /api/v1/access-requests/mine`: requester's currently visible requests.
- `GET /api/v1/access-requests/inbox`: pending requests the actor can currently approve.
- `POST /api/v1/access-requests/{id}/approve|deny`: reason and optional valid_until; CSRF-protected. Repeated decision returns 409.
- Discovery: query 2–200 characters, result limit 1–50, bounded 1,000 DB candidates, literal escaped filename matching. Read responses use no-store.

UI has request forms on known documents and discoverable metadata, own-request history, shared approval inbox, decision reasons and optional shortened expiry. No unrelated approval workflow or multiple-approver requirement is introduced.

## Transaction/audit contract

Migration 0012 records pending/approved/denied requests, decision actor/time/reason and the resulting ACL ID. A partial unique index prevents duplicate pending requests per user/document/permission. Document then request row locks serialize decisions. ACLAdministrationService supports an internal `commit=False` option with the same checks and audit; approval commits the ACL and request state atomically only after both change_acl and access_approved audit writes. Audit failure rolls both changes back. Request/denial actions emit access_request/access_denied, with correlation/user/resource/IP/UA context. Requests and decisions retain history.

## Validation

Local suite, PostgreSQL 17 upgrade/check/downgrade/upgrade and authorization coverage gate run after this phase. Positive/negative tests cover IDOR/CSRF, literal/minimal discovery, strict ancestor hiding, default-deny discovery, owner/manager approval, delegated ACL-admin rejection, exact permission, bounded expiry, DENY precedence, disabled requester, policy blocks, duplicate requests, audit rollback and five concurrent decisions producing exactly one ACL. Frontend typecheck/lint/build and backend Ruff/mypy/Bandit/secret/dependency checks pass. CI reruns the complete regressions plus storage/scanner/search/Redis integrations.
