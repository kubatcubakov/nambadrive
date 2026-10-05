# Current repository state

Implementation checkpoint: 2026-10-05. Working branch `codex/phases-5-22`, draft PR #2, stacked on unmerged phases 2–4. No production deployment or merge.

| Phase | Implementation / validation |
|---|---|
| 0 | Foundation implemented |
| 1 | OIDC/session/CSRF implemented; real user Authentik acceptance pending |
| 2–4 | Organization, resource tree, central AuthorizationService implemented; PostgreSQL/ACL gates green |
| 5 | Immutable S3 adapter; real SeaweedFS 4.48 and CI green |
| 6 | Quarantine/durable AV queue; real ClamAV 1.5.4 clean/EICAR and CI green |
| 7 | Metadata/document operations/raster preview/trash; local/PostgreSQL/CI green |
| 8 | Numbered immutable versions/current+2; PostgreSQL concurrency and immutability checks green |
| 9 | Signed ONLYOFFICE sessions/callbacks, create Office files; protocol/security CI green; live co-edit runtime acceptance pending |
| 10 | Tika/OpenSearch indexing/search with fresh ACL; real engines and CI green |
| 11 | Internal/external shares, hashed tokens, passwords/rate limits/atomic usage; PostgreSQL and real Redis CI green |
| 12 | Owner/manager access requests, minimal discovery, temporary ACL; local/PostgreSQL/CI green |
| 13 | Retention policies, historical Legal Hold, governed internal cleanup; local/PostgreSQL/CI green |
| 14 | User/department/project quotas, durable allocation journal; local/PostgreSQL/CI green |
| 15 | Private notifications, durable outbox, email/TLS and Telegram admin alerts; local/PostgreSQL/CI green |
| 16 | Contextual durable audit and Wazuh integration; local/PostgreSQL/real Wazuh CI green |
| 17 | Quarterly owner/manager reviews, snapshots and audited revoke decisions; all seven CI jobs green |
| 18 | Private SCIM provisioning, disabled-user revocation and audited ownership transfer/queue; local/PostgreSQL gates green, CI required before Phase 19 |
| 19–22 | Pending |

Phase 13 validation: 443 local tests passed (12 opt-in runtime skips); 424 PostgreSQL regression tests passed, including immutable retention and hold/cleanup serialization. Authorization coverage remains above 90%. Migration upgrade/check/downgrade/upgrade, Ruff/mypy/Bandit/secret/dependency checks and frontend typecheck/lint/build pass. Per-phase documentation records exact APIs and validation boundaries.

Phase 18 validation: 534 local tests passed (17 opt-in runtime skips), 520 PostgreSQL tests passed (one Redis runtime skip). Authorization coverage 95.88% local / 94.48% PostgreSQL. Migration roundtrip, lint/typecheck/build, Bandit/secret/dependency checks green. See docs/phase18-identity-lifecycle.md.

Release work still required: complete dashboard/Drive UI, backup/restore, deployment profiles/security hardening and full acceptance/performance/security testing. Real Authentik and live ONLYOFFICE remain explicit external/runtime acceptance boundaries. Existing partial Compose configuration is not a production-ready stack.
