# Approved architecture

## Components
Browser -> reverse proxy -> React frontend / FastAPI backend. Backend uses PostgreSQL, Redis and worker. Worker integrates ClamAV, Tika, OpenSearch and SeaweedFS. ONLYOFFICE is a separate document service. Audit JSONL is harvested by host Wazuh Agent.

## Authoritative stores
- PostgreSQL: identity mapping, metadata, resources, ACL, roles, sessions, retention/legal-hold metadata, shares, requests, notifications.
- SeaweedFS: binary document versions only.
- OpenSearch: derived search index, rebuildable, never authoritative for access.
- JSONL/Wazuh: authoritative application audit stream.

## Trust boundaries
User network sees only HTTPS reverse proxy endpoints for NambaDrive and browser-required ONLYOFFICE. PostgreSQL, Redis, OpenSearch, Tika, ClamAV and SeaweedFS S3/admin ports are internal only.

## Upload flow
Browser -> Backend authentication/CREATE/quota/type/size -> quarantine -> ClamAV. Clean -> immutable object in data bucket -> DB version/checksum -> Tika -> OpenSearch -> ACTIVE. Infected remains quarantine + security event. ClamAV outage keeps files quarantined.

## Download flow
Browser -> Backend -> authorization DOWNLOAD -> audit -> backend streams object from SeaweedFS. Never Browser -> SeaweedFS.

## ONLYOFFICE flow
Backend checks EDIT and generates signed ONLYOFFICE config. ONLYOFFICE fetches document through short-lived NambaDrive internal document endpoint and saves through validated callback. Save creates new immutable S3 version and reindexes. JWT mandatory.

## Search flow
Browser -> Backend -> OpenSearch candidates -> AuthorizationService filter -> Browser.

## Immutable object model
Key `<space_uuid>/<document_uuid>/<version_uuid>`. Filename is metadata, not object path. Rename/move is metadata-only.

## Graceful degradation
OpenSearch down: documents work, search unavailable. Tika down: indexing queues/retries. SMTP/Telegram down: notifications retry. ClamAV down: new uploads remain quarantined. ONLYOFFICE down: editing unavailable but other permitted file operations continue. PostgreSQL down: protected operations stop/fail closed.
