# Phase 1 changelog

Version: `0.1.0`

Added:

- Authentik OIDC Authorization Code login with PKCE S256.
- Redis-backed one-time login transaction (`state`, `nonce`, verifier).
- Strict discovery issuer validation.
- JWKS signature validation and JWT algorithm allowlist.
- PostgreSQL `users` and `application_sessions` tables.
- Identity keyed by immutable OIDC `sub`.
- Opaque application-session cookie; only SHA-256 stored in DB.
- CSRF protection foundation for state-changing endpoints.
- Login/logout/current-user frontend flow.
- Dedicated JSON audit events for login, login failure and logout.
- Authentik setup documentation.
- CI migration test against PostgreSQL 17.11.

Deferred by design:

- periodic Authentik user-disable synchronization;
- department mapping;
- role/ACL authorization;
- break-glass account;
- S3/documents/ONLYOFFICE.

These are implemented in their approved later phases rather than being faked in Phase 1.
