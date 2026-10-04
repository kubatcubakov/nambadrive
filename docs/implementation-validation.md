# Phases 2–4 validation checkpoint — 2026-10-05

Implementation branch: `codex/phases-2-4`. Source was retrieved from the supplied GitHub repository and its handoff unpacked after SHA-256 verification. AGENTS.md, START_HERE_CODEX.md and all approved specifications were read before implementation. Approved specification files and security invariants are preserved.

## Delivered

- Phase 2: companies, hierarchical departments/sections, PRIMARY/SECONDARY memberships, expiring/revocable multiple managers, explicit organization administration, audit-backed service/API and minimum administration UI; migration 0003.
- Phase 3: UUID security metadata resource tree, ownership, department, ACL inheritance, classification/state, hierarchy validation and PostgreSQL tree trigger; migration 0004. No document binary implementation.
- Phase 4: one AuthorizationService, structured decisions, roles/defaults/scoped bindings, timed USER/DEPARTMENT/ROLE ACL, DENY precedence, hard policy, inherited retention/Legal Hold, scoped audited maximum-one-hour Break Glass, protected resource/ACL/binding APIs, minimum resource/ACL UI and trusted first-admin bootstrap; migration 0005.

## Executed local gates

| Gate | Result |
| --- | --- |
| Backend tests | 272 passed, 1 PostgreSQL-specific test skipped |
| Authorization package statement + branch coverage | 96.43%; required >=90% |
| Backend Ruff | Passed |
| Strict mypy | Passed, 40 source files |
| Frontend TypeScript, ESLint, production build | Passed |
| SQLite migrations | Phase-by-phase upgrade/downgrade/upgrade and final full roundtrip passed |
| Migration/model drift check | Passed on fresh SQLite database |
| PostgreSQL 17.11 migrations | Upgrade/downgrade/upgrade and schema drift checks passed |
| PostgreSQL authorization/API/trigger regression | 257 passed; service statement + branch coverage 94.86% |
| Bandit application SAST | Passed |
| Source credential-pattern scan | Passed |
| Backend dependency audit | No known vulnerabilities; editable application source scanned by Bandit |
| Frontend npm audit | Zero vulnerabilities |
| Bootstrap shell syntax / tracked diff whitespace | Passed |

Initial validation found pre-existing Python typing errors, a TypeScript configuration error and vulnerable pip/pytest tooling; those were corrected. UUID columns now use SQLAlchemy's native portable UUID type, preserving PostgreSQL UUID storage while making SQLite migration/model validation accurate. The handoff script was made compatible with macOS base64/checksum tools without changing its expected checksum.

## Unvalidated runtime boundaries

PostgreSQL 17.11 was installed and tested with a disposable database reachable only through a private Unix socket (no TCP listener or autostart). Runtime checks found missing ORM declarations for existing unique constraints on Authentik subject and session hash; the models now reflect those constraints without removing database protections. Docker and real Authentik remain unavailable locally. Container scanning, ZAP and real OIDC integration remain deployment/release checks; no production deployment or administrator bootstrap was performed. Tests cover SQLite and real PostgreSQL, with controlled authentication/session stubs; they do not imply real Authentik acceptance.

GitHub Actions and GitLab CI enforce coverage, lint/typechecks, migration tests, Bandit, dependency and credential scans. The PostgreSQL job uses a disposable database; its authorization tests use rolled-back outer transactions to retain the migrated trigger/schema and isolate each test.

Phase 5 and later phases were not started. All later document operations must use AuthorizationService and retain the mandatory green authorization regression gate.
