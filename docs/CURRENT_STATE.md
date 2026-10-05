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
| 18 | Private SCIM provisioning, disabled-user revocation and audited ownership transfer/queue; all seven CI jobs green |
| 19 | Responsive Drive navigation, private favorites/recent, visible-only pagination and admin dashboard; all seven CI jobs green, including Chromium |
| 20 | Encrypted independent cold bundles, durable WAL hook and isolated real PostgreSQL/SeaweedFS restore; all eight CI jobs green, including real Linux backup/restore |
| 21 | Fresh authorization/OIDC/logging hardening and complete pinned deployment profiles; all nine CI gates green, zero Critical/High trust bypass; visible vendor High review documented |
| 22 | OIDC/API/session/CSRF acceptance, real 100-user HTTP/PG metadata load and isolated HTTPS ZAP gate implemented; final CI/external UAT pending |

Phase 13 validation: 443 local tests passed (12 opt-in runtime skips); 424 PostgreSQL regression tests passed, including immutable retention and hold/cleanup serialization. Authorization coverage remains above 90%. Migration upgrade/check/downgrade/upgrade, Ruff/mypy/Bandit/secret/dependency checks and frontend typecheck/lint/build pass. Per-phase documentation records exact APIs and validation boundaries.

Phase 18 validation: 534 local tests passed (17 opt-in runtime skips), 520 PostgreSQL tests passed (one Redis runtime skip). Authorization coverage 95.88% local / 94.48% PostgreSQL. Migration roundtrip, lint/typecheck/build, Bandit/secret/dependency checks green. See docs/phase18-identity-lifecycle.md.

Phase 19 validation: 542 local / 528 PostgreSQL tests passed; authorization coverage 95.88% / 95.35%. Migration roundtrip and all lint/security/dependency/frontend gates green; three Chromium desktop/mobile UI smoke tests passed with simulated API fixtures. See docs/phase19-drive-dashboard.md.

Phase 20 validation: 551 local regression tests plus ten backup unit cases passed; 528 PostgreSQL regressions, migration roundtrip, Chromium and security/dependency gates green. Authorization coverage 95.88% local / 94.48% PostgreSQL. Real PG17.11/Seaweed4.48 recovery proved archived WAL replay beyond basebackup, object SHA-256 and preserved Legal Hold/quarantine/default-deny. Tiny fixture restore took 24.333 seconds; representative 500 GB RPO/RTO acceptance remains pending. See docs/phase20-backup-restore.md.

Phase 21 validation: 574 local tests plus an editor-session revocation regression passed (17 opt-in skips), 95.88% authorization coverage; 550 PostgreSQL tests plus the editor-session regression, migration roundtrip, Ruff/mypy/Bandit/secret/dependency/frontend/Chromium gates pass. Complete per-host Compose files and actual image builds/container scans are required in CI before Phase 22. See docs/phase21-hardening.md.

Release work still required: final acceptance/performance/ZAP/security testing and real infrastructure/provider runtime acceptance. Real Authentik and live ONLYOFFICE remain explicit external/runtime acceptance boundaries. Complete Compose service definitions now require actual private TLS/firewall/credentials/failover acceptance before any production readiness claim.

Phase 22 implementation: signed OIDC and exhaustive protected-route acceptance plus real session/CSRF checks; real 100-user HTTP/PostgreSQL metadata load (1,000 requests, 500 owner allows/500 cross-owner denials, p95 0.5705s locally), no auth/audit overrides. CI runs ZAP on the built app behind its actual HTTPS gateway. Final automated CI and real provider/Office/multi-host/500GB acceptance remain pending. See docs/phase22-acceptance.md.
