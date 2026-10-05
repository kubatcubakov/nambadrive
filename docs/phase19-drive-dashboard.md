# Phase 19 — Drive navigation and administration

Responsive React application separates My Documents, Shared Spaces, Departments, Shared With Me (all authorized documents owned by another user), Recent, Favorites, Access Requests, Quarterly Reviews, Trash, Notifications, Search, Profile and Administration. Browser links still require server sessions and current ACL. No auth/share secrets are stored in browser storage.

## Drive data

`GET /api/v1/drive?view=mine|spaces|departments|shared|recent|favorites|trash&page=1` returns up to 100 authorized resources, names, owner/department display names, classification, current size and own favorite flag. Optional department_id narrows only the resource candidates; it never grants rights. Default Departments filters the user's organizational memberships. Every returned resource requires fresh central VIEW (RESTORE for Trash), valid resource/org state, policies and inheritance. System/Storage admin gets no content through these lists. Empty document shells without a current clean version are excluded from flat active document lists.

Page positions count visible rows only; hidden entries neither consume a slot nor reveal a hidden total. Internal candidates scan in 200-row database batches. No search score, raw storage URL or inaccessible metadata is returned. Names render as escaped React text. Responses are no-store. Directory browsing retains the resource tree API and live permission checks.

`PUT/DELETE /favorites/{resource UUID}` are CSRF protected and operate only on the session user's bookmarks. Addition needs VIEW; removal of one's own stale bookmark does not disclose document metadata. Idempotency is serialized. Favorites and Recent are filtered again after ACL revocation, disabled-user lifecycle, policy/classification or state changes. RecentDocument is updated only after a successful audited document VIEW; it is not a new authorization grant. No API reads another user's bookmarks/history.

`GET /resources/{UUID}/capabilities` requires VIEW and returns allowed permission names from AuthorizationService; frontend action visibility does not enforce access. Reader has no download action without DOWNLOAD. Existing document endpoints remain authoritative for actions. A failed document open clears the previous detail to avoid stale metadata presentation.

## Editing and policy

Directory UI supports folder creation, bulk upload and DOCX/XLSX/PPTX creation when the parent capabilities allow. Existing signed Office editing, previews, downloads, versions, links, move/copy/trash/restore remain available under their separate permissions. Metadata form includes project, counterparty, contract number/date/expiry, tags and description; owner/department remain required authoritative fields.

`PUT /resources/{UUID}/security` requires CHANGE_ACL, CSRF and nonempty reason to change classification/inherit_acl. Hard policy and central authorization apply before mutation. All old/new values are durably audited; audit failure rolls back policy and share revocations. Classification changes revoke existing external links throughout the affected subtree so returning to PUBLIC cannot resurrect older links. Anonymous sharing still requires PUBLIC at every ancestor. Legal Hold, retention deadlines and binary/version state are not edited by this endpoint. ACL/role UI uses the existing audited grant/revoke endpoints; sysadmin has no implicit resource CHANGE_ACL.

## Administration

`GET /admin/dashboard` is gated by central RECEIVE_ADMIN_ALERTS and returns aggregate user/document/AV queue/notification/review/ownership transfer metrics and logical bytes, including unmatched durable reservations. It returns no filenames, document UUIDs, search content or credentials. Counts are observations, not a claim that dependencies are healthy. `/drive/capabilities` exposes own configuration/organization capabilities for navigation.

Administrator tabs separate overview, identity lifecycle/fallback, organization, spaces/ACL, retention/Legal Hold and quotas. Organization-only administrators see only organization configuration. Per-resource ACL controls remain available to authorized owners/managers. Profile contains own identity, usage and notification preferences. No production deployment or merge action is provided.

## Validation

Migration 0019 creates private Favorite/RecentDocument tables. Positive/negative SQLite/PostgreSQL tests cover IDOR, user isolation, revoked favorites/history, membership without VIEW, admin content denial, reader download separation, CSRF, security policy audit rollback, share revocation and visible-only pagination. Previous authorization and security suites remain mandatory at >=90% coverage.

Playwright Chromium smoke tests run against the actual React application with explicitly simulated API fixtures: navigation/favorites, reader capability buttons, separate admin dashboard, 390px mobile overflow and stale-detail clearing after 403. Screenshots are inspected locally. These tests are UI contracts, not real Authentik/Office runtime acceptance. Framework setup follows [Playwright web server](https://playwright.dev/docs/test-webserver) and [API mocking](https://playwright.dev/docs/mock). CI installs Chromium and runs `npm run test:ui`; no fixture route is included in the production backend.
