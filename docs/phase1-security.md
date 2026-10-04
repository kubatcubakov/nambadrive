# Phase 1 security decisions

- OIDC Authorization Code + PKCE S256.
- Authentik MFA remains authoritative.
- Login transaction is short-lived in Redis.
- Callback state is bound to both Redis transaction and browser HttpOnly state cookie.
- OIDC provider metadata issuer must match configured issuer exactly.
- Only explicitly allowed JWT signature algorithms are accepted (`RS256` by default).
- ID token requires `exp`, `iat`, `iss`, `aud`, `sub`, and `nonce`.
- User identity key is OIDC `sub`; email and username are attributes only.
- Browser does not receive persistent Authentik tokens from NambaDrive.
- NambaDrive application-session token is random and opaque.
- Database stores only SHA-256 of application-session token.
- Session cookie is HttpOnly, SameSite=Lax; Secure must be enabled in production.
- CSRF token is HMAC-derived from active application session.
- Logout requires a valid CSRF token.
- Login/login-failed/logout events are written to dedicated JSON audit stream.
- Raw session tokens, OIDC tokens and OIDC client secret must never be logged.
- Direct backend port remains unexposed in AIO; trusted forwarded IP headers therefore come only through the reverse proxy in the supported topology.
