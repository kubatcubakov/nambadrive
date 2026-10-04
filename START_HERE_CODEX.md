# Start here in Codex

First, if the source tree has not been unpacked yet, run:

```bash
bash bootstrap_handoff.sh
```

Then read `AGENTS.md` and all files under `docs/approved/` first.

Continue NambaDrive v1.0 from the current repository. Treat the approved specs as binding. Do not simplify security controls. Inspect current code before changing it.

Current implementation is Phase 0 + Phase 1 identity only; Phase 2+ is not implemented.

Continue with:
1. Phase 2 organization structure
2. Phase 3 unified resource tree
3. Phase 4 AuthorizationService

For each phase create Alembic migrations, backend services/API, frontend minimum admin UI where appropriate, tests, documentation, and CI checks.

Do not proceed past the ACL phase unless the authorization regression suite is green. Never expose PostgreSQL/Redis/OpenSearch/SeaweedFS directly to user network and never introduce direct browser-to-S3 access.

If Docker or external Authentik is unavailable in the coding environment, continue implementation and automated tests that do not require the external service; clearly report the unvalidated runtime boundary instead of weakening the implementation.
