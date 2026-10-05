# Phase 18 — Authentik disabled-user lifecycle

## Identity contract

Private `/scim/v2` SCIM 2.0 Users provisioning accepts a dedicated bearer secret (`NAMBADRIVE_SCIM_TOKEN`, at least 43 characters; generate 32 random bytes with `secrets.token_urlsafe(32)`). Missing/short token denies all requests. Authentication is centralized in AuthorizationService. Public nginx explicitly denies `/scim/`; configure a private TLS reverse proxy reachable only by Authentik, forwarding to backend. Never expose backend's port to the user network. Production network deployment is completed in Phase 21.

`externalId` MUST equal the exact immutable OIDC `sub`. Default Authentik hashed-user-ID subject matches default SCIM externalId. Configure an explicit mapping for another immutable subject mode; never use email/username subject modes. Profile changes update the same local UUID; PUT with another externalId returns 409. POST of an existing identity returns 409. A username filter may discover an account, but cannot replace its external identity. With SCIM configured, login requires prior provisioning; OIDC cannot create unknown users or enable disabled users. With SCIM absent, DEV first-login provisioning remains available.

Primary integration references: [Authentik SCIM provider](https://docs.goauthentik.io/add-secure-apps/providers/scim/) and [SCIM HTTP protocol RFC 7644](https://www.rfc-editor.org/rfc/rfc7644.html). Authentik sends user updates using PUT. This endpoint advertises only Users, filtering, and PUT/DELETE, no PATCH/bulk/groups. Configure group property mapping to skip all groups: organization and membership remain administered in NambaDrive. Check ServiceProviderConfig capability negotiation on the installed Authentik version; do not falsely advertise unsupported bulk/PATCH. Real user's Authentik acceptance remains pending.

## Operations

### Optional creation on first OIDC login

At the operator's explicit request, set `NAMBADRIVE_OIDC_JIT_PROVISIONING=true` on
the backend to create an unknown local user after a fully validated OIDC callback,
without waiting for an initial SCIM synchronization. The default is `false`, so
existing deployments retain their prior-provisioning requirement. No migration is
required. Set the flag in the Compose override, rebuild the backend image, and
recreate the backend; setting the variable on older code has no effect.

The immutable OIDC `sub` remains the only identity key. Matching email or username
does not link to another account. New accounts receive no administrator, manager,
department membership, role binding or document ACL grants. Existing disabled
accounts remain blocked and cannot be re-enabled by OIDC. First login uses the
existing serialized governance lock and unique subject constraint, and session
creation and the durable login audit still precede transaction commit.

This option changes initial account creation only. It does not replace the approved
disabled-user lifecycle: trusted Authentik disable notifications through SCIM are
still required to revoke existing sessions/shares and transfer ownership promptly.
Removing that channel requires a separately implemented and validated equivalent;
an OIDC login alone cannot revoke already-issued NambaDrive sessions when an
account is later disabled. Keep the SCIM token and lifecycle controls configured.

- `GET /scim/v2/ServiceProviderConfig`, `GET /Users` with pagination (max 100) and exact `externalId eq "..."` or `userName eq "..."` filters; `GET /Users/{local UUID}`.
- `POST /Users`, `PUT /Users/{local UUID}` require externalId/userName/strict boolean active; optional displayName/emails. Names/email never identify principals. Validation errors use SCIM Error envelopes, no submitted payload reflection.
- `DELETE /Users/{local UUID}` deactivates; never deletes database identities/documents.
- Application administrator `GET /api/v1/identity`, CSRF-protected `PUT /identity/policy` with enabled global_owner_id/reason, `POST /identity/{UUID}/disable`. Central MANAGE_IDENTITY capability requires SYSTEM_ADMIN; no document access is implied. It cannot be assigned through document ACL or Break Glass.
- Admin UI selects global fallback owner and displays unresolved transfer count. No API enables accounts; trusted provisioning is required.

## Disable and ownership

One transaction disables the user; revokes application/Office sessions, creator external shares, direct USER ACL (ALLOW and DENY), local role bindings, Department Manager and Break Glass grants, and organization-admin capability. Membership stays organizational metadata; it confers no access while disabled. Re-enable does not resurrect revoked grants or sessions. Every identity change/revocation/ownership transfer has durable audit; ACL changes include old/new values. Audit failure rolls the entire database operation back and returns error, for provider retry.

Transfer every unpurged owned SPACE/FOLDER/DOCUMENT including quarantined/trash/held resources. Selection: first active manager in nearest enabled department/ancestor department (ties sorted by immutable user UUID), otherwise enabled Space Owner, otherwise explicitly configured enabled Global Document Owner. No first-admin/email heuristic. Retention, holds, classification, hierarchy and immutable version bytes stay unchanged; ownership transfer is not physical cleanup. Quota accounting follows new owner, and security transfer is not rejected by an allocation quota.

If all successors are unavailable, the account remains disabled, grants are revoked and a durable transfer queue retains resource/previous owner UUIDs. No timeout restores access. `python -m app.lifecycle.worker` retries every minute; policy configuration retries immediately. Re-enable returns 409 until prior ownership has been transferred, preventing restoration of old owner rights. Administrators configure the fallback through the reviewed UI; no user decision is needed to implement or test this boundary.

PostgreSQL governance lock precedes user/resource/grant locks across lifecycle, OIDC/session creation, ACL/role assignment, sharing and manager assignment. Concurrent login either precedes disable and is revoked, or fails after disable. Credential/token/audit data are never returned by the administrator status endpoint.

## Validation

Local and PostgreSQL positive/negative regression tests cover provisioning/authentication, immutable identity conflicts, strict booleans/filters, disable/re-enable, sessions/Office/external-share/Break Glass/direct grants, manager/space/global fallback, holds/classification preservation, missing fallback queue, audit rollback, system-admin absence of content rights, CSRF and concurrent login/disable. Run the full migration upgrade/check/downgrade/upgrade and the previous phase suites. Real Authentik propagation latency and private TLS delivery must be measured during deployment acceptance; unit/API tests do not validate those external boundaries.
