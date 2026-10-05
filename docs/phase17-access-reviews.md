# Phase 17 — quarterly access review

`python -m app.access_reviews.worker` creates one review per active resource and UTC calendar quarter, in batches of 100. The due time is the beginning of the next quarter. A unique resource/quarter constraint and the shared governance lock prevent competing schedulers from duplicating work. Overdue reviews remain visible and never automatically revoke access. Completed reviews are historical records; the next quarter creates a separate review. Notifications go to current authorized owners/managers via the Phase 15 collector.

Review authority is central AuthorizationService's owner/ancestor-owner or Department Manager decision for CHANGE_ACL, subject to hard policy and valid resource/user/organization. An ordinary ACL administrator, system-admin label or emergency grant alone cannot approve a review. Lists/details filter by current authority; an owner transfer changes who can review without giving old owners continued access.

The snapshot includes direct ACL assignments, applicable inherited ACL with inheritance boundaries, relevant role bindings/permissions, ancestor ownership and department-manager system grants. These are **assignments, not a claim of effective access**: DENY, state and policies still apply centrally. Global administrative role labels without applicable grants are excluded. Each source has a stable key and canonical SHA-256 snapshot fingerprint. Refresh adds changed/new snapshots, supersedes obsolete undecided entries and preserves prior user decisions. An automatically superseded pending source that returns unchanged becomes pending again. Completed reviews cannot be refreshed or changed by API.

KEEP acknowledges the reviewed assignment; it does not create or extend a grant. REVOKE uses the existing ACL administration service, with its fresh authorization at the source resource, and commits ACL change plus review decision atomically after durable audits. A child owner cannot revoke a parent's inherited assignment without CHANGE_ACL authority on that parent. Ownership, department-manager and global role grants require their dedicated administration workflow and cannot be erased through ordinary ACL review. The UI states this restriction. Revoke of a DENY is an explicit authorized ACL change, never an automatic result of expiry/overdue review.

Review actions hold governance, hierarchy/source and review row locks. Changed grants produce 409 and require explicit snapshot refresh. Completion requires a KEEP decision matching every current source and no undecided items; revoked sources must actually be absent. New grants since the snapshot block completion. Reviews are point-in-time assessments; subsequent legitimate ACL changes remain audited and will appear in the next review. Historical decisions are not retroactively interpreted as approval of later changes.

## API / UI

- `GET /api/v1/access-reviews`: permitted reviews with quarter/deadline/completion/overdue state.
- `GET /api/v1/access-reviews/{id}`: snapshots, decisions, reasons and whether source revocation is permitted.
- `POST .../{id}/refresh`: explicit update of an incomplete snapshot.
- `POST .../{id}/items/{item_id}`: KEEP or REVOKE, reason required.
- `POST .../{id}/complete`: validates current assignments before historical completion.

All mutations require CSRF. Responses use no-store. The UI lists deadlines, displays source/principal/permission/effect, accepts reasons and separates system/inherited restrictions from ordinary revoke actions. No direct physical cleanup or content access is granted.

Tests cover quarter boundaries, idempotent scheduling, owner-only notifications, admin-without-content/review access, IDOR/CSRF, stale/new grants, source authority, system grants, atomic ACL/audit rollback, overdue non-revocation and concurrent PostgreSQL scheduling/decisions. Schema migration is 0017_access_reviews; Phase 16 required no new schema revision.

Validation: 513 local tests passed (16 opt-in skips), 498 PostgreSQL tests passed (one Redis opt-in skip); authorization coverage 95.82% / 94.40%. Full migration roundtrip/schema check, Ruff/mypy/Bandit/secret/dependency audits and frontend typecheck/lint/build pass. Phase CI must be green before Phase 18.
