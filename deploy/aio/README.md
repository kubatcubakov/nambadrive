# NambaDrive AIO — Phase 1

This profile is for development, UAT and pilot deployment.

## 1. Configure

```bash
cp .env.example .env
```

Replace every `CHANGE_ME*` value and configure the real Authentik provider.

Generate a CSRF secret, for example:

```bash
openssl rand -hex 32
```

## 2. Start

```bash
docker compose --env-file .env up -d --build
```

## 3. Migrate

```bash
docker compose --env-file .env run --rm backend alembic upgrade head
```

## 4. Verify

```bash
curl http://localhost:8080/api/v1/health/live
curl http://localhost:8080/api/v1/health/ready
```

Then open the NambaDrive URL and use **Войти через Authentik**.

PostgreSQL and Redis are not published to the host network.
