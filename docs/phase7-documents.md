# Phase 7 — document operations

The document API adds metadata, raster previews, verified downloads, rename, move, copy, trash and restore. Each route obtains an AuthorizationService decision; writes require CSRF. A separate RESTORE permission is explicitly seeded with no ordinary role defaults. It permits evaluation on a trashed document while ancestor state, hard policies, user validity and ACL remain enforced; restoration additionally requires CREATE at the original parent. Trash never physically deletes bytes and is allowed under hold; PURGE remains blocked.

Routes under `/api/v1/documents`:
- GET `/{id}`: VIEW; metadata including current clean version size/hash/type.
- GET `/{id}/preview?page=0`: PREVIEW; PNG raster only, PDF/JPG/PNG/TXT and supported text formats. No active PDF/HTML is returned. PDF/image renderer runs in a 30-second subprocess; Linux also caps CPU/address space. Pixel limits and metadata stripping apply.
- GET `/{id}/download`: DOWNLOAD; full SHA-256 verification before streaming an attachment with no-store/nosniff headers. Never a storage URL.
- PUT `/{id}/metadata`: EDIT; project/counterparty/contract details/tags/description.
- POST `/{id}/rename`: RENAME; filename validation and unchanged extension.
- POST `/{id}/move`, `/{id}/copy`: MOVE/COPY and destination CREATE; same-company destination only. Classification, hold, retention and inherited hard prohibitions are conservatively preserved. Move retains old object keys; copy creates a new UUID version after verifying identical clean content.
- DELETE `/{id}`: DELETE, soft trash only.
- GET `/trash`, POST `/{id}/restore`: RESTORE, filtered listing and audited restore.

Migration 0007 adds optional metadata and RESTORE permission. Department/owner/type remain mandatory resource/version metadata. New browser file navigation provides bulk upload, details, preview/download only when allowed, metadata editing, rename, destination picker and trash/restore. Server decisions always take precedence over cached UI permissions.

Tests cover all new endpoints against IDOR, CSRF, reader PREVIEW without DOWNLOAD, corruption before download, audit rollback, and preservation of classification/hold/retention/hard policy across copy/move. PDF and image raster rendering are exercised against real libraries. No physical purge, Office editor or version replacement is introduced by this phase.
