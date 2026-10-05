# Approved implementation roadmap

0. Foundation — DONE.
1. Authentik identity/session/CSRF — IMPLEMENTED, real Authentik runtime validation pending but user authorized continuing without it.
2. Organization structure — NEXT.
3. Unified resource tree.
4. Authorization/ACL engine — mandatory green regression suite before document access.
5. SeaweedFS adapter.
6. Upload + ClamAV.
7. Document metadata/preview/download/rename/move/copy/trash/restore.
8. Versions/checksums/current+2 previous.
9. ONLYOFFICE Community Development/MVP integration/co-edit/save-as-version.
10. Tika/OpenSearch search with ACL filtering.
11. Internal/external sharing.
12. Access requests and temporary grants.
13. Retention + Legal Hold + purge worker.
14. User/department/project quotas.
15. In-app/email/Telegram(admin/security) notifications.
16. Complete audit/Wazuh rules/integration.
17. Quarterly access review.
18. Authentik disabled-user lifecycle and ownership transfer.
19. Admin dashboard.
20. Backup/restore tooling and runbooks.
21. Security hardening.
22. Acceptance/security/performance/dependency tests.

Feature Definition of Done: implementation, authorization checks, positive+negative tests, audit where needed, API docs, UI where needed, errors, no secret leakage, migration where needed, review/CI green.

Do not feature-creep after governance milestone until production/security acceptance is complete.
