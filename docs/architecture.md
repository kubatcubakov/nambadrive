# Architecture status

The complete NambaDrive v1.0 architecture was approved before implementation.

Phase 0 intentionally contains no document or ACL business logic. The first security-critical module will be introduced only after Authentik/OIDC and organizational structure foundations are in place.

Core invariants that future code must preserve:

- Default DENY
- backend-only authorization decisions
- no direct browser-to-S3 access
- explicit ACL DENY beats ACL ALLOW
- retention/legal hold cannot be bypassed by ordinary ownership
- audit is separate from application logging
