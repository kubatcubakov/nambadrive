# Phase 2 organization

Company -> Department -> Section uses a same-company parent hierarchy. Creation is append-only in this phase: reparent/delete is not exposed, so cycles and dangling subjects cannot be introduced through API. Users have at most one PRIMARY and any number of SECONDARY memberships. Multiple managers are supported with UTC activation/expiry and historical revocation. Assignment locks the subject user; DB enforces membership uniqueness.

All `/api/v1/admin/organization` endpoints require an enabled authenticated session and an explicit local organization-administrator capability. Mutations also require CSRF. Identity claims and Department Manager status never confer this capability. Bootstrap the first capability using a trusted database operator against the immutable mapped user UUID; no public self-promotion endpoint exists. This capability grants no document access. A later role binding model remains distinct from this capability.

GET lists companies, departments, memberships and manager history. POST `/companies` and `/departments` create hierarchy nodes. PUT `/departments/{id}/assignments` accepts user_id, PRIMARY/SECONDARY/MANAGER and optional timezone-aware valid_until. DELETE `/departments/{id}/managers/{user_id}` records historical revocation.

Every mutation flushes, writes and fsyncs audit, then commits. Audit failure raises and request dependency rolls back. Audit includes actor, correlation ID, IP, UA, old/new assignment and result. No raw identity/session tokens are included.

Local gate: 10 backend tests pass; ruff, strict mypy and Bandit pass; SQLite upgrade/downgrade/upgrade passed and PostgreSQL migration SQL generated. PostgreSQL 17.11 migration roundtrip and schema drift validation subsequently passed; real Authentik runtime validation remains pending.
