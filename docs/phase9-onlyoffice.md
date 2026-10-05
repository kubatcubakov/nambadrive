# Phase 9 — ONLYOFFICE Community integration

The backend signs editor configurations after EDIT and live application-session checks. Short-lived Office sessions bind an actor, application login, shared co-editing room and immutable base version. Concurrent editors join one document key. New external versions make old room callbacks stale. Download/print/clipboard permissions come from AuthorizationService; Office Download As also requires EXPORT_PDF because that menu includes PDF conversion. Original download remains the separate backend DOWNLOAD endpoint.

Routes:
- POST `/office/{document_id}/session`: authenticated EDIT + CSRF; signed config, script URL and expiry.
- POST `/office/create`: authenticated destination CREATE + CSRF; valid blank DOCX/XLSX/PPTX generated server-side and uploaded through ClamAV quarantine.
- GET `/office/internal/content/{session_id}`: ONLYOFFICE outbox JWT covering the exact internal URL, live login/Office session, EDIT and base-version integrity. No browser cookie or browser-config JWT can replace the server signature.
- POST `/office/internal/callback/{session_id}`: outbox JWT; body must exactly match signed payload. Checks document key, room/session/login expiry, current version, all room participants' current EDIT permission, file type and allowlisted download origin/path. Redirects and environment proxies are disabled. Callbacks cannot fetch arbitrary URLs.

Save statuses 2/6 enter the same immutable upload/quarantine/AV path, retaining the original EDIT authorization basis in immutable version metadata. A durable unique callback receipt and new version are committed together; retries are idempotent. Status 2 closes the room; a new room waits for the queued save's scan. Status 4 closes without changes. Error statuses never create content. An expired/revoked participant conservatively blocks the room save; reopen a fresh room after resolving access. The browser destroys the editor when its lease expires; server checks remain authoritative.

Deploy ONLYOFFICE Community for DEV/MVP using the official supported server. Browser access goes to its HTTPS office origin. Document content and callback traffic must use a private backend origin. The edge nginx explicitly rejects `/api/v1/office/internal/`. Keep backend ports private.

Merge `deploy/aio/onlyoffice/local.example.json` into the server's `local.json` with independently generated >=32-byte browser/inbox and outbox secrets. Match `NAMBADRIVE_OFFICE_BROWSER_SECRET` and `NAMBADRIVE_OFFICE_OUTBOX_SECRET`; never commit real values. Configure JWT outbox expiration (5m), Authorization header, all JWT validation enabled, and preserve these settings across container entrypoint regeneration/upgrades. Restart ONLYOFFICE services after configuration. Set OFFICE_PUBLIC_URL, OFFICE_INTERNAL_URL and OFFICE_BACKEND_URL under the NAMBADRIVE_ prefix. Missing/identical signing keys fail closed. Full profile wiring is completed during hardening.

Protocol references: [signature configuration](https://api.onlyoffice.com/docs/docs-api/additional-api/signature/), [outbox header payload](https://api.onlyoffice.com/docs/docs-api/additional-api/signature/request/token-in-header/), [callback status contract](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/).

Validation: signed callback/content contract, token substitution, stale/revoked/disabled sessions, hard policy, SSRF, body tampering, quarantine/idempotency and audit atomicity; real Office-format template libraries. A live ONLYOFFICE browser co-edit/save cycle remains an integration acceptance boundary: no Docker engine is available locally. This is not represented as runtime-validated by contract tests.
