# File-focused interface (October 2026)

Approved visual direction: Dropbox-style file navigation and table, a document workspace with an adjacent information/access/version panel, and organization administration through named selections. Existing API contracts, authentication, CSRF and server authorization remain authoritative.

## Changes

- Compact navigation, user avatar, search/notification shortcuts, file table with owner/department, size and favorites; responsive mobile layout.
- Folder toolbar separates **Create** and **Upload files**. Upload destination stays the opened folder; uploads remain quarantined until scanning completes.
- Document toolbar and separate **Information**, **Access**, **Versions** panels. New-version upload is explicitly described as replacing content with the same format. Supported raster formats alone offer preview; Office documents use the existing ONLYOFFICE integration.
- Organization company selector and department tree, membership/manager/structure tabs, separate company and department names, validation before empty submissions, named employee selection when the existing identity endpoint permits it. Membership and manager authority remain distinct.
- Resource creation hides irrelevant controls when configuring an existing resource. Departments and ACL recipients have named selectors when the existing endpoints permit listing. Advanced permissions remain available in an expandable section.

## Security boundaries

No backend/schema/API changes are included. System administrators do not gain document read access. UI actions remain dependent on capabilities and API authorization. The identity list retains its existing MANAGE_IDENTITY authorization; an organization administrator without that capability sees an explicit identifier fallback rather than a broadened user-list endpoint. ACL recipient IDs and resource IDs remain available in advanced administration. No live editor save acceptance is claimed: the user's pilot currently opens the document but reports a callback/save warning; investigation is deferred at the user's request.

## Validation

TypeScript/Vite build, ESLint, secret scan, backend suite including branch authorization coverage, and Chromium UI regression tests. Browser tests cover backend-driven visibility and revocation, responsive layout, named organization assignments with unchanged CSRF/PUT contract, distinct folder upload and version controls, and unsupported Office raster preview suppression. Browser tests use mocked API responses and do not replace real end-to-end runtime acceptance.

The UI branch is based on `codex/oidc-jit-provisioning` so that the user's opted-in account creation behavior is preserved. It does not merge or deploy either change.

## Mockup fidelity correction

After reviewing the installed pilot UI, the first iteration was found to retain a stacked search block and a document card below the file table. The refinement moves the existing search form into the global header (React portal, unchanged search API), makes an open document replace the file table, places metadata/access/version panels beside its workspace, collapses editable metadata forms, and groups secondary navigation under Workflows. File icons, typography, spacing, classification badges and named file selection are adjusted to the approved concept. No DOCX raster preview is fabricated; Office content still requires the signed ONLYOFFICE flow.

The browser regression explicitly checks that the document title appears near the top of the viewport and that folder upload/list controls disappear in document mode. Revocation is rechecked through the document refresh action, which clears previously shown detail before retrying the authorized API.

## Separate editor tab and collapsed document panel

The editor action opens `/?editor=<document_uuid>` in a separate tab with
`noopener noreferrer`. This authenticated application view contains the editor
and a return action; the signed Office session and CSRF flow are unchanged.
The editor fills the available viewport, without the Drive sidebar.

The document information/access/version panel starts collapsed for each document
and is controlled by an accessible toggle. Share opens the access panel.
No authorization grants or backend API contracts change.

Validation: seven Chromium UI tests, TypeScript/Vite build, ESLint and secret scan.
Real editor rendering and saving on the pilot remain a user-run check after update.
