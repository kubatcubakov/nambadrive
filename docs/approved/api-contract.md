# Approved API contract summary

Base `/api/v1`, REST/JSON, UUID public identifiers, HttpOnly session cookie, CSRF for state-changing requests, correlation ID on every request.

Error envelope: `{"error":{"code":"...","message":"...","correlation_id":"..."}}`.

Core groups:
- `/auth`: login, callback, me, csrf, logout.
- `/spaces`, `/folders`, `/documents`, `/resources`.
- `/search`, `/access-requests`, `/shares`, `/favorites`, `/notifications`, `/access-reviews`, `/office`, `/admin`.

Protected resource endpoints always call AuthorizationService. `GET document` -> VIEW; preview -> PREVIEW; download -> DOWNLOAD; Office session -> EDIT; move -> MOVE + destination CREATE; copy -> COPY + destination CREATE; delete -> DELETE; version history -> VIEW_VERSION_HISTORY; restore version -> RESTORE_VERSION; share -> SHARE; ACL -> CHANGE_ACL.

No endpoint returns permanent S3 URL. No browser access to OpenSearch/S3/DB/Tika/ClamAV.

Upload returns async/quarantine state and is not accessible as active content until clean.

ONLYOFFICE uses dedicated signed short-lived internal document access and callback endpoints with validation/idempotency.

External share raw token is returned only on creation; DB stores hash. Share password never appears in query string.

Physical purge has no ordinary user API and is policy-driven by background worker.
