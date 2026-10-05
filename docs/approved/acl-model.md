# Approved data/security model and ACL engine

## Unified resource tree
All protected objects use one `resources` hierarchy with UUID, `resource_type` SPACE/FOLDER/DOCUMENT, `parent_id`, `owner_user_id`, `department_id`, `inherit_acl`, timestamps and soft-delete fields.

## Identity/org tables
`users`, `departments` (hierarchical), `department_memberships` (PRIMARY/SECONDARY), `department_managers` (may be multiple, may expire).

## ACL
`acl_entries(resource_id, principal_type USER|DEPARTMENT|ROLE, principal_id, permission_id, effect ALLOW|DENY, applies_to_self, propagate_to_children, valid_from, valid_until, source, created_by, revoked_at, reason)`.

## Roles/bindings
`roles`, `permissions`, `role_permissions`, `role_bindings`.
Ownership is not an ACL row; it is a system grant from resource ownership. Department Manager is also an organizational system grant.

## Authorization algorithm
For `authorize(user, permission, resource)`:
1. Disabled/missing user or invalid session -> DENY.
2. Invalid/inaccessible resource state -> DENY.
3. Hard security policy denial -> DENY.
4. Retention/Legal Hold constraints -> DENY where applicable.
5. Valid scoped Break Glass -> ALLOW only covered allowed permissions.
6. Resource/ancestor owner or Department Manager grant -> ALLOW subject to hard policy.
7. Classification restrictions apply.
8. Collect valid explicit/inherited ACL for all user principals; if any applicable DENY -> DENY; else any ALLOW -> ALLOW.
9. Valid role binding grant -> ALLOW where not otherwise denied.
10. Default DENY.

Return a structured decision `{decision, permission, reason, resource_id, source_resource_id, principal_type, principal_id}` when applicable.

## Retention/Legal Hold
Soft delete may be allowed while retention/hold active, but physical PURGE is blocked. Legal Hold wins over everyone including Break Glass. Hold release is historical update, never silent row deletion.

## Version model
`document_versions` has new UUID/object for every version; restore creates a new current version. Normal retention current + 2 previous, subject to retention/legal hold.

## Quota
Quota usage counts physical current/previous/soft-deleted versions until purged. Quota reservation/check must be concurrency-safe.
