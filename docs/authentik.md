# NambaDrive Phase 1 — Authentik OIDC

NambaDrive uses OAuth2/OIDC Authorization Code flow with PKCE. MFA is enforced by Authentik, not by NambaDrive.

## Authentik provider

Create an OAuth2/OpenID Provider for NambaDrive.

Recommended values:

- Application slug: `nambadrive`
- Client type: Confidential
- Redirect URI (DEV example): `http://<NAMBADRIVE_HOST>:8080/api/v1/auth/callback`
- Redirect URI (PROD example): `https://drive.nambagroup.net/api/v1/auth/callback`
- Scopes: `openid profile email`
- Signing key: use the Authentik provider signing key
- Issuer mode: per-provider/default is recommended

With the default per-provider issuer mode, Authentik normally exposes:

- Issuer: `https://AUTHENTIK/application/o/nambadrive/`
- Discovery: `https://AUTHENTIK/application/o/nambadrive/.well-known/openid-configuration`

NambaDrive reads authorization, token and JWKS endpoints from the discovery document and refuses discovery metadata whose `issuer` does not exactly match `NAMBADRIVE_OIDC_ISSUER`.

## Environment

Set in `deploy/aio/.env`:

```env
NAMBADRIVE_PUBLIC_URL=http://drive-dev.example.local:8080
NAMBADRIVE_OIDC_ISSUER=https://auth.example.local/application/o/nambadrive/
NAMBADRIVE_OIDC_DISCOVERY_URL=https://auth.example.local/application/o/nambadrive/.well-known/openid-configuration
NAMBADRIVE_OIDC_CLIENT_ID=nambadrive
NAMBADRIVE_OIDC_CLIENT_SECRET=<secret>
NAMBADRIVE_CSRF_SECRET=<long-random-secret>
NAMBADRIVE_COOKIE_SECURE=false
```

For production HTTPS:

```env
NAMBADRIVE_PUBLIC_URL=https://drive.nambagroup.net
NAMBADRIVE_COOKIE_SECURE=true
```

## Security properties

The browser never stores OIDC access or ID tokens.

Login transaction:

1. NambaDrive creates random `state`, `nonce`, PKCE verifier.
2. Transaction is stored in Redis for 10 minutes.
3. Browser receives only a short-lived HttpOnly state cookie.
4. Callback must match both Redis state and browser cookie.
5. Backend exchanges authorization code with PKCE verifier.
6. Backend validates ID token signature, issuer, audience, exp, iat, sub and nonce.
7. User is mapped by immutable OIDC `sub`.
8. NambaDrive creates its own random application session.
9. Only the opaque application-session token is stored in a Secure/HttpOnly cookie.
10. Database stores SHA-256 of the session token, not the raw value.

State-changing requests use a CSRF token derived server-side from the active session and `NAMBADRIVE_CSRF_SECRET`.

## Test sequence

```bash
cp deploy/aio/.env.example deploy/aio/.env
# edit real Authentik settings and secrets

docker compose --env-file deploy/aio/.env -f deploy/aio/compose.yml up -d --build

docker compose --env-file deploy/aio/.env -f deploy/aio/compose.yml \
  run --rm backend alembic upgrade head
```

Open the configured `NAMBADRIVE_PUBLIC_URL`, click **Войти через Authentik**, complete MFA, and return to NambaDrive.

Check database:

```sql
SELECT id, authentik_sub, username, email, enabled, last_login_at
FROM users;

SELECT user_id, created_at, expires_at, revoked_at, ip
FROM application_sessions;
```

Check audit:

```bash
docker compose --env-file deploy/aio/.env -f deploy/aio/compose.yml \
  exec backend tail -f /var/log/nambadrive/audit.json
```

Expected events include `login`, `login_failed`, and `logout`.
