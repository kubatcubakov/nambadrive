# Phase 4 AuthorizationService

Every exposed resource API evaluates AuthorizationService. Organization administration uses an explicit local capability checked by the same service. Authentication/session and CSRF enforcement remain server-side; role names from browser or OIDC claims are not trusted.

Evaluation: valid enabled persisted user and session; valid resource and organization hierarchy/state; global/ancestor hard policy; inherited retention/Legal Hold and 30-day Trash eligibility for PURGE; valid scoped durable-audited Break Glass; resource/ancestor ownership and scoped Department Manager system grants; classification controls; applicable explicit/inherited ordinary ACL with any DENY winning; eligible role defaults; default DENY. Decisions include decision, permission, reason, resource UUID, source UUID and principal where applicable. DB failure raises/error, never ALLOW.

`inherit_acl=false` stops ordinary ACL and scoped role bindings above that node. It never stops hard policy, ownership, retention or Legal Hold. Membership principals use enabled departments/companies; managers cover their department subtree, not siblings. Ordinary ACL DENY does not override the higher-priority ownership/manager system grants, as required by the approved evaluation order.

Anonymous external-share permission is hard denied unless the entire resource path is PUBLIC. No sharing API is implemented yet. Strictly Confidential sensitive operations (DOWNLOAD/PRINT/CLIPBOARD_COPY/EXPORT_PDF) and request-access discovery receive no role-default access and require explicit ACL where policy permits. Ownership/manager and valid Break Glass remain system grants at their approved earlier evaluation positions.

System/Storage/Security Admin and owner role labels have no implicit document role permissions. EDITOR defaults VIEW/PREVIEW/EDIT/UPLOAD_NEW_VERSION; REVIEWER and READER default VIEW/PREVIEW; GUEST requires explicit ACL. Ownership is a resource field, not an ordinary owner role binding. Scoped EDITOR/REVIEWER/READER/GUEST assignments require CHANGE_ACL. Global administrator bindings are not exposed in the ordinary resource API.

## API

- GET `/resources`, `/{id}`: filtered VIEW metadata.
- POST `/resources`: CREATE_SPACE or parent CREATE_FOLDER/CREATE, plus CSRF.
- GET `/{id}/permissions/{permission}`: current actor decision after VIEW.
- GET/POST `/{id}/acl`, DELETE `/{id}/acl/{entry_id}`: CHANGE_ACL, mutations require CSRF; revoke preserves history.
- GET/POST `/{id}/role-bindings`, DELETE `/{id}/role-bindings/{binding_id}`: CHANGE_ACL, mutations require CSRF.
- POST `/{id}/break-glass`: global SYSTEM_ADMIN, CSRF, nonblank reason, one allowlisted permission, 1–60 minutes, scoped to resource descendants. Hard policy and hold/retention checks still precede the grant. Forbidden emergency permissions include PURGE, SHARE, EXTERNAL_SHARE, CHANGE_ACL and CREATE_SPACE.

ACL/role/manager changes and emergency grants flush, durably fsync their audit record, then commit. Failure rolls the transaction back. Audit contains old/new state, actor, correlation ID, resource, IP, UA and result. Exception envelopes are sanitized; every HTTP response includes X-Correlation-ID. Raw session/OIDC/share tokens are never included.

## Bootstrap and validation

After migrations and the user's first Authentik login maps an immutable subject to a user UUID, a trusted local operator can run from backend:

```sh
python -m app.authorization.bootstrap --user <mapped-user-uuid> --reason 'Initial approved administrator'
```

This PostgreSQL-only command initializes the first organization administrator and global SYSTEM_ADMIN binding with durable audit before commit. It refuses disabled/missing users and an already-initialized administrator, and does not grant document ACL. It has no HTTP equivalent. It was not executed against a real deployment.

Run `pytest -q backend/tests --cov=app.authorization --cov-branch --cov-fail-under=90`. Both GitHub Actions and GitLab CI enforce the coverage gate and lint/typechecks, SQLite migration roundtrips, PostgreSQL 17 migrations/schema drift checks, Bandit, dependency audits and source credential-pattern scanning. PostgreSQL-specific tests require `NAMBADRIVE_TEST_POSTGRES=1` against a disposable migrated CI database.

PostgreSQL 17.11 migration roundtrips, schema drift checks, resource trigger tests and the authorization/API regression suite passed locally against an isolated Unix-socket-only database. Real Authentik/container/ZAP checks remain pending. Phase 5 was not started at this checkpoint.
