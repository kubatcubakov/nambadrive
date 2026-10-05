# Phase 22 — acceptance, security and performance

Phase 21 was completed before starting this phase: commit `d9d65cab8dbf432fb57747f52df4aceafe32fd1d`, [all nine CI gates green](https://github.com/kubatcubakov/nambadrive/actions/runs/37304404074). Its final scan found zero Critical and zero High authentication/authorization/trust bypasses. Remaining visible High findings are documented in Phase 21; this is not a claim of zero High vulnerabilities.

## Automated acceptance

- `test_acceptance_identity.py`: actual RSA-2048 signatures; issuer/audience/nonce/exp/iat/authorized-party validation; all required claims; payload tampering, unsigned and symmetric tokens; unknown-key refresh and fail-closed missing key. PKCE is checked against the exact verifier, state is atomically consumed once, and the HTTP callback binds browser state, issues a fresh Secure/HttpOnly/SameSite session and stores only its hash. The provider transport is a fixture: this does not establish live Authentik interoperability or MFA acceptance.
- `test_acceptance_routes.py`: enumerates current OpenAPI operations and sends anonymous requests to every protected route, including SCIM and trusted Office routes. Missing browser session, Office signature or provisioning configuration deny/error; no hidden identifiers are returned. New protected routes automatically join the inventory. Public health/login/callback/share-capability entry points have their own validation contracts and are not treated as ordinary authenticated APIs.
- All previous positive/negative ACL, document, worker, audit, lifecycle and PostgreSQL trigger/concurrency suites remain mandatory. This phase does not add a migration: there is no new application schema. Migration upgrade/check/downgrade/upgrade still run.
- `scripts/acceptance/load.py`: a separate empty database named **nambadrive_acceptance**, explicit isolation flag, 100 virtual users with distinct real server-side sessions, real Uvicorn HTTP and PostgreSQL. 1,000 metadata resource requests must produce exactly 500 owner allows and 500 cross-owner denials, with no unexpected results/identifier leakage. No authorization overrides, shared request sessions or mocked audit are used. Engineering regression budget p95 <=5 seconds and total <=180 seconds; these are test budgets, not an approved production SLO.
- `scripts/acceptance/zap.sh`: actual OWASP ZAP passive baseline against the built frontend/backend behind the actual app HTTPS gateway template. Ephemeral internal Docker network, generated one-day test certificate, no public ports, no real identities or credentials. The image is pinned by digest. Missing/malformed output, tool errors and any Medium/High alert fail the gate; Low/Info remain visible artifacts. The gateway CSP no longer permits inline styles (the frontend uses CSS classes).

The ZAP baseline is **unauthenticated and passive**, not an authenticated active penetration test. It examines the actual HTTPS application surface and headers; signed session/protected API behavior is exercised by the separate tests above and earlier object-level negative suites. Do not interpret ZAP's absence of authenticated findings as validation of authenticated user workflows. No real session or share capability is supplied to or exported in scanner artifacts.

Local initial performance measurement (Mac development machine, small metadata fixture): 100 users, 1,000 requests, zero unexpected results; p50 0.3746s, p95 0.5705s, maximum 0.8691s, 231.96 requests/s over 4.311s. CI generates its own `load.json`; hardware-dependent measurements must not be presented as production capacity.

## Requirement-to-evidence matrix

| Approved requirement | Automated evidence | External runtime boundary |
| --- | --- | --- |
| OIDC/session/CSRF; immutable `sub`; disabled identities | identity acceptance, auth security, lifecycle, hardening | Real Authentik provider/MFA/SCIM disable |
| Organization and full department-manager scope | organization, authorization, PostgreSQL | Actual organization data and managers |
| One resource tree and default-deny centralized ACL | authorization, resource API, route inventory, PostgreSQL | UAT role/department matrix sign-off |
| Owner/manager, DENY, inheritance, temporary grants, Break Glass, strict classification | authorization and governance positive/negative suites, >=90% coverage | UAT policy sign-off |
| Immutable UUID/SHA versions and quarantine until clean | storage/upload/versions, real SeaweedFS/ClamAV, PostgreSQL | Production topology, disk and AV operations |
| Metadata, raster previews, document operations, Trash | documents, versions, Drive and Chromium | Representative documents/mobile browsers |
| Signed Office integration and save-to-quarantine | office protocol/security/session-revocation tests | Live co-edit, conversion, save and Community capacity |
| ACL-filtered search, no OCR or inaccessible snippets | search, real Tika 4.1.0/OpenSearch, integration | Real-language/document corpus |
| Hashed shares, expiry/max views/password limits | shares and Redis/PostgreSQL concurrency | User-facing links/password workflow |
| Owner/manager access requests and minimal discovery | access requests, PostgreSQL audit/concurrency | Approval workflow sign-off |
| Historical Legal Hold/retention, guarded purge | governance, PostgreSQL triggers/concurrency | Real retention policies and held data |
| Quotas, durable reservations, versions charged | quotas, upload/version failure/concurrency | Actual capacity and quota administration |
| Private notifications and durable retry | notifications positive/negative/outbox suites | SMTP/Telegram delivery credentials and receipt |
| Durable contextual audit, fail-closed critical operations | audit rollback/filesystem tests, real Wazuh decoder/rule tests | Host agent forwarding, off-host receipt/disk alerts |
| Quarterly access reviews; no automatic overdue revoke | access reviews and PostgreSQL | Owner review sign-off |
| Admin dashboard without implicit content grants | Drive/admin/identity/Chromium and authorization tests | Admin usability review |
| Independent encrypted backup, basebackup + archived WAL, SHA recovery | backup units and actual PG17/SeaweedFS restore | 500GB RPO <=24h/RTO <=4h; quarterly operational restore |
| Three profiles, private services, TLS/security controls | Compose policy/parse, actual builds, SAST/SCA/container/secret gates, ZAP | Multi-host certificates/firewalls/replication/quorum and node outage |
| <=100 users / ~500GB | 100-user metadata HTTP load | Binary/Office load and representative 500GB hardware |

## Final UAT prerequisites

Automated implementation can proceed without these, but production acceptance cannot be signed off until an isolated UAT environment supplies:
1. Authentik issuer/client/SCIM mapping, test users with MFA and a disable/re-enable scenario.
2. ONLYOFFICE test origin and TLS trust, representative DOCX/XLSX/PPTX, two editor accounts and signed save/AV confirmation.
3. Private host addresses, certificates, firewall allowlists, storage volumes/quorum and independent encrypted backup target/key custody.
4. SMTP/Telegram test destinations and Wazuh manager/agent receipt.
5. Representative dataset/hardware and policy owners to confirm capacity, RPO/RTO, role matrix and mobile workflows.

Keep secrets in the approved private mounts/vault, never Git, reports or chat logs. Production merge/deployment requires the user's separate permission. No production deployment, merge or external notification is executed by these tests.
