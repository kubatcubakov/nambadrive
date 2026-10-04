# Approved requirements — NambaDrive v1.0

## Purpose
Secure corporate file server, not a full BPM/DMS in v1. Central document storage with matrix-based authorization, web Office editing, search, audit, retention and controlled sharing.

## Identity and organization
- Authentik OIDC, MFA entirely in Authentik.
- Users assigned to organization structure in NambaDrive UI: Company -> Department -> Unit/Section.
- A user may belong to multiple departments.
- One or more Department Owners/Managers can be assigned.
- Department Manager automatically has full operational access to department documents, subject to hard security policy/Retention/Legal Hold.
- Document owner is initial uploader/creator.

## Permissions
VIEW, PREVIEW, CREATE, EDIT, RENAME, MOVE, COPY, DELETE, DOWNLOAD, PRINT, CLIPBOARD_COPY, UPLOAD_NEW_VERSION, CREATE_FOLDER, SHARE, CHANGE_ACL, VIEW_VERSION_HISTORY, RESTORE_VERSION, EXPORT_PDF.

## Roles
SYSTEM_ADMIN, STORAGE_ADMIN, SECURITY_ADMIN reserved v2, SPACE_OWNER, FOLDER_OWNER, DOCUMENT_OWNER, EDITOR, REVIEWER, READER, GUEST.

System/Storage administrator must not automatically read document content. Emergency Break Glass is audited, reason-required, maximum 1 hour.

## ACL
- Inheritance from parent resources.
- `inherit_acl=false` breaks inheritance.
- Ordinary ACL conflict: DENY wins.
- Temporary ACL with expiry.
- Access can be assigned to user, department or role.

## Download controls
For v1, when download is denied remove UI action and block API/direct storage access. Watermark/DRM is out of scope v1.

## Delete/versioning
- Soft delete, Trash 30 days.
- Document owner, folder owner and authorized admins may initiate delete subject to policy.
- Current version + 2 previous versions normally.
- New edits/uploads create immutable versions.

## Supported formats
DOCX, XLSX, PPTX, PDF, ZIP, JPG, PNG, DWG, PSD, TXT, CSV, JSON, XML.
Preview required for PDF/JPG/PNG/TXT. Create DOCX/XLSX/PPTX from UI. Co-edit Office files in browser with ONLYOFFICE Docs Community during Development/MVP.

## Storage
On-prem SeaweedFS with S3 API. Browser never receives S3 credentials/permanent S3 URL. Backend/worker/ONLYOFFICE trusted flow accesses object storage. SHA-256 stored for every immutable version.

## Metadata
Required: owner, department, document type. Optional: project, counterparty, contract number/date/expiry, confidentiality, tags, description.

## Classification
PUBLIC, INTERNAL, CONFIDENTIAL, STRICTLY_CONFIDENTIAL.
Anonymous external share only for PUBLIC. Strictly Confidential is not visible in request-access discovery without ACL.

## Search
Filename + full text in DOCX/XLSX/PDF and approved text formats through Tika/OpenSearch. No OCR in v1. Every search result is backend ACL filtered.

## Audit
Mandatory JSONL audit; app cannot edit/delete audit records. Wazuh Agent collects file. Record identity/IP/UA/time/correlation/resource/result and old/new ACL where relevant.

## Sharing
Internal link requires login and live ACL check. External anonymous share allowed only under policy; expiry default 7d max 30d; optional password, max views, view/download, revoke.

## Access request
Users can request VIEW, EDIT, DOWNLOAD. Request goes to owner/manager; one authorized approver is enough. Temporary access expiry supported.

## UI
Google Drive-like browser UI: My Documents, Shared spaces, Departments, Shared with me, Recent, Favorites, Access Requests, Trash, Notifications, Search, Profile, Administration. Responsive mobile web; no desktop app v1.

## Upload/AV
Default max file size 500 MB configurable. Bulk upload. ClamAV mandatory: quarantine until clean. Infected files stay quarantined 30 days, unavailable to normal users, audit/Wazuh alert.

## Quotas
Per user/department/project. Versions count toward quota. On exceeded quota block upload and notify user/admin.

## Access review
Quarterly. Owner reviews principals/permissions and keeps/revokes. Overdue review does not automatically revoke in v1.

## Disabled user lifecycle
When disabled in Authentik: revoke app sessions and external shares, deactivate direct ACL, transfer ownership Department Owner -> Space Owner -> Global Document Owner, audit all actions.

## Retention / Legal Hold
Admin-configurable policies by folder/type/space/document. Example contracts 5 years. Legal Hold supported and cannot be bypassed. Physical purge only after Trash period, retention expiry and no Legal Hold.

## Compliance context
Designed for an organization subject to NBKR and PCI DSS controls; PCI DSS documentation may be stored, but cardholder PAN/CVV/SAD storage is not a target use case.

## Scale
<=100 users, ~500 GB initial logical data.
