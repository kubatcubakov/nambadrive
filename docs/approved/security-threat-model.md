# Approved security threat model summary

Priority threats: IDOR, ACL bypass, direct S3/OpenSearch access, search leakage, OIDC/session theft, CSRF/XSS, path traversal, MIME confusion, malicious/ZIP-bomb upload, ClamAV outage race, ONLYOFFICE callback spoof/replay, stale editor sessions, share token brute force/leakage, quota race, SSRF, secret/log leakage, audit tampering/full disk, malicious insider/admin, ransomware, backup compromise.

Required controls/tests:
- object-level negative authorization tests for every protected endpoint.
- ACL conflict/inheritance/owner/manager/disabled/expired/breakglass/retention/legal-hold regression tests.
- no direct user connectivity to PostgreSQL/Redis/OpenSearch/Tika/ClamAV/SeaweedFS.
- OIDC verify state, nonce, PKCE, issuer, audience, signature, exp/iat.
- Secure+HttpOnly+SameSite session cookie, new session after login, raw session token not persisted.
- server-side MIME validation and filename normalization, UUID S3 keys.
- EICAR test; AV outage remains quarantine; archive bomb limits.
- ONLYOFFICE JWT/session/document-key validation and callback idempotency.
- 256-bit equivalent share token entropy, stored as hash, rate limit password attempts.
- audit JSON encoding, no raw secrets/tokens, critical security changes fail closed if durable audit unavailable.
- backup restore test and SHA-256 validation.
- OWASP ZAP against test environment before production; SAST/dependency/container/secret scanning in CI.

Release security acceptance: 0 unresolved Critical, 0 High authorization bypass, 0 direct S3 exposure, 0 unauthenticated protected API, 0 ACL/Legal-Hold/Retention bypass, 0 secrets in Git, 0 critical audit bypass.
