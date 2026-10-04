# Phase 3 unified security resource tree

`resources` is the single UUID tree for SPACE -> FOLDER -> DOCUMENT. A folder may contain folders and documents; documents cannot contain children. Spaces are roots. Required ownership and department references use foreign keys. Ownership is assigned to the creator. ACL inheritance is explicit; classification, ACTIVE/QUARANTINED/TRASH state, soft-delete timestamps and timestamps are stored.

The metadata service rejects missing parents, invalid types/classifications, inaccessible ancestors, cross-company children and cycles. Parent locking protects creation against concurrent changes. PostgreSQL also uses a serialized hierarchy-validation trigger to reject cycles, invalid parent types and conversion of a parent into a document. No move/reparent/delete API is exposed in this phase.

Phase 4 protects GET/list/create `/api/v1/resources` and all ACL operations. Lists filter each resource with AuthorizationService and return no inaccessible counts. Creating a space requires a global SYSTEM_ADMIN binding; folder/document metadata requires CREATE_FOLDER/CREATE on its parent. This creates security metadata only: there are no storage objects, uploads, preview/download/Office endpoints or physical purge API.

Retention and Legal Hold metadata exist solely for the Phase 4 mandatory pre-grant checks. Management and lifecycle remain Phase 13.

Local migration upgrade/downgrade/upgrade and tree tests passed. PostgreSQL 17.11 upgrade/downgrade/upgrade, schema drift checks and trigger runtime tests also passed locally; CI repeats these checks.
