# Phase 11 — internal and external sharing

Internal links require SHARE + VIEW to generate and never grant new access. `POST /api/v1/shares/internal/{document_id}` returns a document navigation path; the recipient must log in via Authentik and every document API rechecks their ACL. UI opens `/?document=UUID` after login.

External shares require SHARE, EXTERNAL_SHARE, VIEW and each delegated PREVIEW/DOWNLOAD permission. AuthorizationService hard-denies EXTERNAL_SHARE unless the document and all ancestors are PUBLIC. No anonymous bypass for administrative roles. Every redemption rechecks the creator's current enabled state, those permissions, resource/ancestor state, hard policy, expiry, revocation and maximum uses. Losing authorization or changing classification blocks an existing token immediately.

## API and UI

- `GET /api/v1/shares/documents/{id}` lists safe metadata with SHARE authorization. No token or password hashes.
- `POST /api/v1/shares/documents/{id}` (CSRF): `days` default 7, 1–30; optional password 12–128 characters, optional `max_views` 1–1,000,000, `allow_view` default true, `allow_download` default false. At least one operation is required.
- `DELETE /api/v1/shares/documents/{id}/{share_id}` (CSRF, SHARE) revokes without deleting history. It does not require PUBLIC classification, allowing revocation after reclassification.
- `POST /api/v1/shares/access` takes token/password as secret body fields, action `preview|download` and optional zero-based PDF page. No login or ambient cookie authority is used. Successful preview returns raster PNG; download returns a verified attachment. No direct S3 URL. Unsupported preview formats return 415; Office anonymous co-edit is not granted by a share.

The Drive UI creates internal/external links, sets password/expiry/limits/download and revokes existing links. The public `/share#TOKEN` page sends the capability only in JSON request bodies. It removes the fragment from browser history on load, keeps it only in component memory, and does not use local/session storage. Every successful preview page or download consumes one use, including repeated operations. Failed password/auth/storage/render/audit attempts do not consume a use. A refreshed share page must be reopened from the original full link. The link creator sees the raw token once and must retain the generated link if needed.

## Security and transaction contract

Tokens use `secrets.token_urlsafe(32)` (256 bits); only SHA-256 hashes are stored, with a unique index. Passwords use random 128-bit salts and PBKDF2-HMAC-SHA256 at 600,000 iterations with constant-time digest comparison, matching the [OWASP PBKDF2 work-factor guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Password hashing runs outside the async event loop. Passwords/tokens are SecretStr at the API boundary and never audit fields.

Redis atomically limits all external access attempts: 120/min global, 30/min observed client address, 10/min capability hash. Counters expire even on worker failure. Client-provided forwarding headers are not trusted here. Redis outage fails closed with 503; exceeded limits return 429. Production reverse-proxy trusted-address configuration is part of Phase 21.

Document then share row locks serialize revocation/usage, including concurrent requests for the final allowed use. Authorization runs again after verified storage/preview processing, immediately before durable audit and DB commit. Creation/revoke audit is fail closed; failed audit rolls back. Preview/download also returns no bytes on audit failure. Application/PG enforce maximum 30-day lifetime; the central authorization path independently rejects imported/malformed longer grants. Bodies and metadata use no-store; anonymous output adds nosniff, sandbox and no-referrer headers. Copying previously received bytes cannot be revoked; DRM is outside approved v1 scope.

## Validation

395 local tests, 373 PostgreSQL tests before the opt-in Redis runtime test; authorization module coverage 96.39%, PostgreSQL service 94.94%. Migration upgrade/check/downgrade/upgrade, Ruff/mypy/Bandit/secret scan, dependency audits and frontend typecheck/lint/build passed. Tests cover IDOR/CSRF, PUBLIC ancestor restriction, wrong password, view/download separation, creator ACL withdrawal/disable, expiry/revoke, hard policy, trash, critical audit rollback, hash secrecy and five concurrent final-use requests (exactly one succeeds). CI also runs the real Redis atomic rate-limiter test. No production deployment or live Authentik acceptance is implied.
