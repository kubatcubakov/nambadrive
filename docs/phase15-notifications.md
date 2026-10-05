# Phase 15 — private notifications and durable delivery

`python -m app.notifications.worker` produces notifications from committed quota incidents, pending/decided access requests, infected versions and audited Break Glass grants. A PostgreSQL advisory producer lock plus source receipts and unique recipient/event constraints prevent duplicate fanout across concurrent workers. Receipts, in-app notifications and channel outbox rows commit together. Rolled-back operations do not produce notifications; independently durable quota incidents survive failed allocation transactions. The existing approval inbox and notification fanout reach currently authorized owners/managers. One approver remains sufficient.

The user's enabled account owns its notification inbox. In-app messages are static descriptions without document names/content, tokens or free-text request reasons. A document UUID/link is returned only after a fresh central VIEW check. Administrative alerts require the separate global RECEIVE_ADMIN_ALERTS decision (SYSTEM_ADMIN, subject to global hard policy; no content grant, no ordinary ACL or Break Glass grant). Disabled users cannot read notices or receive delivery. Admin permission and email preferences are rechecked before each send. An ordinary user cannot direct alerts to an arbitrary recipient/chat.

## Channels and recovery

Email sends a generic new-notification message only to the current identity email. SMTP uses mandatory implicit TLS with certificate/hostname verification, bounded timeout, optional credentials and custom CA. Configure `NAMBADRIVE_SMTP_HOST`, `SMTP_PORT` (465), `SMTP_FROM`, optional `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_CA_FILE`. Prefix every setting with `NAMBADRIVE_`. No plaintext TLS fallback exists. Missing configuration defers delivery; in-app remains usable. Users may opt out of email in the UI.

Telegram is solely for quota/malware/Break Glass administrative alerts, using operator-configured `NAMBADRIVE_TELEGRAM_BOT_TOKEN` and `NAMBADRIVE_TELEGRAM_ADMIN_CHAT_ID`. Keep the configured chat restricted to authorized administrators; remove departed administrators in Telegram as part of identity operations. The endpoint is fixed to api.telegram.org over verified HTTPS; redirects and environment proxies are disabled. No filenames, resource IDs, user identifiers, free text or tokens appear in messages. Do not configure HTTP request/debug logging that records bot-token URLs.

Outbox workers claim rows with PostgreSQL FOR UPDATE SKIP LOCKED. Network failures preserve PENDING with exponential delay capped at one hour. Delivery exceptions and secret-bearing provider bodies are not persisted/logged. Retries continue until delivered or suppressed by current recipient policy. Delivery is at-least-once: a provider success followed by database failure may repeat a generic alert; email reuses its stable Message-ID. It is not possible to promise exactly-once delivery across external providers and PostgreSQL. Producer receipts prevent repeated in-app messages.

## API / UI

- `GET /api/v1/notifications`: latest 100 permitted own notifications, no-store.
- `POST /api/v1/notifications/{id}/read`: own notice only, idempotent; CSRF required.
- `GET|PUT /api/v1/notifications/preferences`: own email preference; PUT requires CSRF.

The UI displays messages/time, authorized document links, read action and email preference. No sender API accepts arbitrary recipients or message text.

Tests cover IDOR/CSRF, disabled users, loss of admin rights, email opt-out, no document disclosure, source rollback, fanout transaction rollback, retry, TLS, header injection, fixed Telegram destination, generic errors and concurrent PostgreSQL producers. SMTP/Telegram transport contracts are tested without sending real external messages; delivery to the organization's configured providers remains deployment acceptance.

Validation: 487 local tests passed (15 opt-in runtime skips), 471 PostgreSQL tests passed (one real-Redis opt-in skip). Authorization coverage 95.77% locally / 94.40% PostgreSQL. Migration roundtrip, schema drift check, Ruff/mypy/Bandit/secret/dependency audits and frontend typecheck/lint/build are green.
