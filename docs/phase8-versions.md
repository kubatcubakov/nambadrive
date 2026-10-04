# Phase 8 — immutable version history

Migration 0008 adds monotonically allocated per-document sequence numbers, a unique current CLEAN version and a deferred pruning timestamp. PostgreSQL rejects changes to content identity, size, SHA-256, original filename/MIME/uploader/creation time/sequence, or a final scan verdict. Unique constraints prevent duplicate sequence numbers or simultaneous current versions. Each upload/restore holds the document row lock through its commit.

New routes:
- GET `/documents/{id}/versions`: VIEW_VERSION_HISTORY, clean retained history only.
- POST `/documents/{id}/versions?filename=...`: UPLOAD_NEW_VERSION + CSRF, bounded binary body, PENDING quarantine response.
- POST `/documents/{id}/versions/{version_id}/restore`: RESTORE_VERSION + CSRF; source must belong to the requested document and be retained/clean. Its verified bytes are copied to a fresh UUID object/version; originals remain untouched.

The current version stays accessible while a replacement is scanned. The worker rechecks UPLOAD_NEW_VERSION immediately before promotion. Malware/AV outage cannot replace current content. Out-of-order scan completion selects the highest clean sequence, never arrival time or UUID ordering. A restored version gets the next sequence and becomes current.

Normal history retains current + two previous clean versions. Older versions receive a 30-day deferred prune timestamp; no bytes are physically deleted here. Effective Legal Hold or unexpired retention preserves all versions. Phase 13 owns actual policy-checked cleanup; deferred candidates still occupy storage/quota until purged.

The UI exposes version history, upload-new-version and restore-as-new only when permitted. Tests cover pending/malware behavior, out-of-order completion, preserved originals, current+2, hold/retention, IDOR/CSRF and PostgreSQL immutable metadata/concurrent uploads/scanners.
