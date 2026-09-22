# A2 — Authentication & Authorization

**Question answered:** who is making this request, and which tenant(s) may
they act as?

Before A2, `X-Tenant-Id` was the *entire* authorization model
(`app.dependencies.get_current_tenant_id`, pre-A2 version): any caller who
sent a real Tenant UUID in that header was trusted as that tenant, no
credential of any kind required. This was A1's top launch blocker — it made
`X-Tenant-Id` a bearer token for every business account in the system.

A2 replaces that with real server-side sessions (Argon2id password hashing,
opaque session tokens, CSRF protection) and an explicit, per-user,
per-tenant `TenantAccess` grant. `X-Tenant-Id` still exists, but it is now
only a **selection hint** — which of the caller's *own* authorized tenants
this request acts as — never authorization on its own.

## The one architectural correction from the original design

The initial A2 design modeled `User → exactly one Tenant` (mirroring the
pre-A2 schema). Before implementation, this was corrected to an explicit
many-to-many relationship instead:

```
User ──< TenantAccess >── Tenant ── Business
```

A `User` row is no longer tenant-scoped at all (no `tenant_id` column,
email unique globally via `uq_users_email`). A `TenantAccess` row is the
*only* thing that grants a user the ability to act as a given tenant
(`unique(user_id, tenant_id)`, plus a per-grant `role`). Knowing a tenant's
UUID — even a real one — grants nothing without a matching `TenantAccess`
row. This lets one operator account hold access to more than one tenant
(an agency managing several client businesses) without weakening isolation
between tenants that don't share a grant.

## Schema

* `users` — `email` (globally unique), `hashed_password` (nullable — a user
  with no password set can never log in; see enumeration-safety below).
* `tenant_access` — `user_id`, `tenant_id`, `role` (`owner` | `operator`),
  `unique(user_id, tenant_id)`. The authorization boundary itself.
* `user_sessions` — `user_id`, `token_hash` (SHA-256 digest of the opaque
  session token — the raw token is never persisted), `csrf_token`,
  `expires_at`, `revoked_at`.

Migration `b1e2f9a08c3d` is purely additive/structural: it does **not**
insert any `User` row. Creating the real production operator account is a
cutover operation performed once, by hand, after this PR merges — never
part of a schema migration.

## Session lifecycle

```
POST /auth/login  (email, password)
        │  UserRepository.get_by_email → verify_password (Argon2id)
        │  unknown email / wrong password / no password set → ONE error,
        │  ONE status (401 invalid_credentials) — never distinguishable
        │  from each other, and a real Argon2 verify always runs (against
        │  a fixed decoy hash for an unknown email) so timing can't
        │  distinguish them either.
        ▼
UserSession row created (token_hash, csrf_token, expires_at)
        │  raw token set as an HttpOnly cookie (never readable by JS)
        │  csrf_token returned ONLY in the JSON response body
        ▼
GET /auth/me        — session restoration on page load (cookie → session)
POST /auth/logout   — revokes the session; idempotent; no CSRF check (see
                       app.routers.auth.logout_route's own docstring for why)
```

`get_current_session` (`app.dependencies`) resolves the cookie to a live,
non-expired, non-revoked `UserSession` and enforces CSRF on every
non-safe-method request. `get_current_tenant_id` builds on it:

```
NO SESSION COOKIE           → 401 not_authenticated
                               (UNLESS legacy_tenant_header_auth_enabled —
                                see Transition compatibility below)
VALID SESSION, tenant IS
  in the user's TenantAccess → tenant_id returned, exactly as before A2
VALID SESSION, tenant NOT
  in the user's TenantAccess → 404 unknown_tenant
TENANT UUID ONLY, no session → 401 not_authenticated (the header alone
                                 never authenticates, real UUID or not)
```

`unknown_tenant` is deliberately the *same* error for "no such Tenant row"
and "a real Tenant this user has no grant for" — telling them apart would
let an authenticated caller enumerate which tenant UUIDs are real.

Every downstream repository/service call continues to receive a plain,
trusted `tenant_id` UUID exactly as before A2 — `get_current_tenant_id`'s
return type and every one of its ~30 call sites are unchanged. That
existing tenant-scoped repository isolation was already an asset; A2 adds
a new check in front of it rather than rewriting it.

## Session token storage

The raw session token (32 bytes, `secrets.token_urlsafe`) is never stored —
only its SHA-256 digest (`token_hash`). A session token has no offline
attacker to slow down the way a password does (it's already 256 bits of
real entropy, not a human-chosen secret), so a plain fast hash is the
right tool here; Argon2id is reserved for passwords, where a slow,
memory-hard KDF is what actually matters.

## CSRF

Because sessions are cookie-based, and the real Studio/API production
topology is genuinely cross-site (Studio has no production deployment
configuration today — only a dev-only Vite server — so production Studio
and API will live on different registrable domains), the cookie must be
`SameSite=None; Secure` in production. That forfeits `SameSite`'s own CSRF
protection, so relying on `SameSite=Lax` alone (which would only be
correct in same-site dev) is not an option.

Instead: a per-session CSRF token is generated at login/session-creation,
returned only in the JSON response body (never in the cookie, never
derivable by a cross-site attacker — CORS blocks a cross-origin page from
reading the response), and required as an `X-CSRF-Token` header on every
non-safe-method authenticated request, checked with `hmac.compare_digest`.
Public endpoints (`/public/businesses/{id}/leads`, `.../events`) and
`/internal/*` have no session concept and are entirely unaffected.

## Cookie flags

```
development: HttpOnly, Secure=False, SameSite=Lax   (localhost, same-site)
production:  HttpOnly, Secure=True,  SameSite=None   (genuinely cross-site)
```

Computed from `settings.environment == "production"` — see
`app.auth.cookies` for the full topology investigation this was based on.

## Transition compatibility

`settings.legacy_tenant_header_auth_enabled` (default `False`) is the only
compatibility path: when `True`, a request presenting **no session cookie
at all** falls back to the pre-A2 "trust `X-Tenant-Id` if the tenant row
exists" behavior. A request that *does* present a session cookie is always
subject to the real session/TenantAccess check regardless of this flag —
there is no way for a caller with a session to get the legacy behavior,
and no way for this flag to silently become a permanent bypass. It exists
only for a deploy-to-cutover window and must be deleted at cutover, along
with the flag itself.

This PR does not flip that flag, does not create the real production
operator `User`/`TenantAccess` row, and does not change how production
`Studio`/API callers authenticate today. **It builds the authentication
boundary; it does not activate it in production.** Cutover happens only
after this PR is reviewed.

## Studio

`src/lib/tenant.ts` (the free-text, localStorage-persisted tenant UUID
input) is deleted entirely. `AppShell` now:

1. Calls `GET /auth/me` once on mount to restore a real session.
2. Shows `LoginScreen` (email/password) when there is no session.
3. Once logged in, offers a `<select>` of *only* the tenants `GET /auth/me`
   returned — never a free-text field, never a client-manufactured list.
4. Sends `credentials: "include"` on every request and `X-CSRF-Token` on
   every mutating one (`src/lib/api.ts`), sourced from the in-memory token
   `login`/`GET /auth/me` returned — never exposed anywhere else in JS,
   and never persisted (a full reload always re-derives it from a fresh
   `GET /auth/me`, the same way the session cookie itself is re-sent
   automatically by the browser).

## Known limitations / deliberately deferred

* No signup, password reset, or MFA — an operator account is created out
  of band by a human with database access, not through any route in this
  system.
* No fine-grained destructive-action policy beyond `owner`/`operator` on
  `TenantAccess` — every authenticated, tenant-authorized caller can
  currently perform any tenant-scoped action, including business
  deletion. The `role` column exists specifically so a future
  owner-vs-operator policy can be layered on without touching
  authentication again.
* `InMemoryRateLimiter` (login rate limiting) is per-process — correct for
  today's single-instance deployment, not for a future multi-instance one
  (same limitation the pre-existing lead-capture/asset-upload rate limits
  already had).
* Session revocation is per-session, not per-user-everywhere; there is no
  "log out all my other sessions" action yet.

## Tests

* `tests/test_auth_api.py` — login/logout/me, enumeration safety, session
  expiry/revocation, rate limiting, cookie flags, CSRF.
* `tests/test_a2_tenant_authorization_matrix.py` — the full User A/User
  B/Tenant A/Tenant B cross-tenant matrix across business, assets, leads,
  reviews, analytics, creative directions, website drafts, domains,
  website versions/rollback, and business deletion.
* `tests/test_a2_public_internal_regression.py` — explicit proof the
  public lead/event/health and `/internal/*` boundaries are unaffected.
* `tests/conftest.py`'s `_bypass_real_authentication_by_default` — every
  pre-existing tenant-scoped test keeps exercising business/repository
  logic via the same `_tenant_id_from_header_unauthenticated` path the
  legacy compatibility flag itself uses, without needing a real login.
* `apps/studio/src/layout/AppShell.test.tsx` — session restoration, login,
  logout, and the authorized-tenant selector.
