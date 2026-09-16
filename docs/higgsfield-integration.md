# Higgsfield integration — configuration

This file documents the environment variables/settings the Higgsfield
integration paths in `apps/api/app/creative/higgsfield/` use, kept
separate from `docs/architecture.md` per that document's own instruction.
**No credentials are committed here or anywhere else in this repository.**

## Status (updated in P2.1)

There are now **three** distinct Higgsfield-related code paths — do not
conflate them:

1. **`HiggsfieldApiCreativeDirector`** (`app.creative.higgsfield.api_client`
   + `app.creative.higgsfield.director`) — **the real, production P2
   Creative Director (P2.1).** Uses the *official* Higgsfield REST API
   (`https://api.higgsfield.ai`), authenticated with a server-side API key
   pair created in [Higgsfield Cloud](https://cloud.higgsfield.ai) —
   `Authorization: Key <KEY_ID>:<KEY_SECRET>`. This is what
   `app.dependencies.get_optional_higgsfield_director` constructs whenever
   `HIGGSFIELD_API_KEY_ID`/`HIGGSFIELD_API_KEY_SECRET` are both set — safe
   to run unattended, unlike path 2 below.
2. **`HiggsfieldCliCreativeDirector`** (`app.creative.higgsfield.cli` +
   `app.creative.higgsfield.director`) — the *original* P2.2/P2.3
   integration, kept for **local development and the manual
   `real_provider` test only** (`tests/test_higgsfield_real.py`), never
   selected in production. Built on the `higgsfield` CLI's own
   already-authenticated local OAuth session (`higgsfield auth login`) —
   see `docs/security.md`'s P2 section for why this remains a documented
   limitation, not a design preference: an unattended production
   deployment has no interactive session to hold that OAuth token.
   Controlled by `higgsfield_cli_enabled`/`higgsfield_cli_binary`/
   `higgsfield_cli_timeout_seconds`, only ever consulted when the REST key
   pair above isn't configured.
3. **`HiggsfieldCreativeProvider`** (`app.creative.higgsfield.provider`) —
   the original P0-era HTTP/API-key-based scaffolding for the *unrelated*
   old CreativeLevel PREMIUM/CINEMATIC tier
   (`app.creative.orchestrator.select_provider`), still wired to that
   older generation path. Every method still raises
   `HiggsfieldNotIntegratedError` — this was never completed and is not
   the P2 Creative Director. `HIGGSFIELD_API_KEY`/`HIGGSFIELD_BASE_URL`
   configure *only* this legacy path; do not confuse them with
   `HIGGSFIELD_API_KEY_ID`/`HIGGSFIELD_API_KEY_SECRET` below.

## REST endpoint verification (P2.1)

Every endpoint path `app.creative.higgsfield.api_client` uses was
confirmed directly against the *official* published OpenAPI spec at
`https://docs.higgsfield.ai/docs/openapi.json` (downloaded and parsed
directly, not summarized) — never invented or guessed:

- `POST /nano-banana` — the reference-image generation endpoint the
  Creative Director uses. Supports `prompt`, `aspect_ratio`, `num_images`,
  and `input_images` (0–8 `{"type": "image_url", "image_url": <https
  URL>}` objects) — exactly the "business logo + real photo references"
  shape the Creative Director workflow needs.
- `GET /requests/{request_id}/status`, `POST /requests/{request_id}/cancel`
  — polling and cancellation.

## Live proof result (P2.1, this pass)

Running the real `real_provider` test (`tests/test_higgsfield_real.py`)
against the API key pair configured for this task surfaced two distinct,
precise, **unbilled** errors — confirmed via a direct raw probe outside
pytest too:

- `POST /nano-banana` → `404 {"detail":"model_not_found"}` — this
  account's API key does not have Nano Banana provisioned, despite the
  endpoint being present in the public OpenAPI spec. Needs confirmation
  from Higgsfield (support or the Cloud dashboard) on whether this
  requires separate model enablement.
- `POST /higgsfield-ai/soul/standard` (probed as a diagnostic — is the
  problem nano-banana-specific or account-wide?) → `403
  {"detail":"not_enough_credits"}` — authentication succeeds, the model
  *is* recognized, but this API key's Higgsfield Cloud workspace has
  insufficient credit balance to run any generation at all.

Neither response included a `request_id`/`status_url` — both were
rejected before ever entering the async pipeline, and Higgsfield's own
documented billing policy ("failed generation requests are not charged")
plus the absence of any accepted request confirms **zero credits were
spent** by either probe. This also answers the earlier open research
question about whether the REST API's credit balance is shared with the
CLI/consumer account: it is evidently **separate** — a Higgsfield Cloud
API-key workspace is its own credit pool, distinct from a personal
account authenticated via `higgsfield auth login`.

**Action needed before a live P2.1 proof can succeed:** add credits to
this API key's Higgsfield Cloud workspace (cloud.higgsfield.ai), and
separately confirm Nano Banana access for that workspace/plan.

**Nano Banana *Pro*** appears as a live job type in the `higgsfield` CLI's
own model catalog (`higgsfield model list`), but **does not appear
anywhere in the public REST OpenAPI spec** — only base `/nano-banana` is
officially exposed via REST today. `HiggsfieldApiClient` refuses to guess
a path for it (`_MODEL_REGISTRY` is a small, explicit allowlist, not a
generic "pass any job_type as a path segment"); using Pro via REST would
require either a documented endpoint appearing later or direct
confirmation from Higgsfield support.

## Model registry — evaluating an alternative to nano-banana (P2.1 continuation)

The `model_not_found` result above never resolved and became a
production blocker: Studio's "Generate creative directions" surfaced
"Higgsfield generation is currently unavailable for this workspace" for
every real business. `app.creative.higgsfield.api_client` now holds an
explicit `HiggsfieldModelConfig` / `_MODEL_REGISTRY` (never a single
hardcoded model) so the production model is a configuration choice
(`HIGGSFIELD_API_MODEL`, see `app.config.Settings`), not a code change.

**Full current image-generation catalog** (from the same published
OpenAPI spec, re-fetched fresh — every video-only model (veo3.1,
kling-video, minimax hailuo, bytedance seedance, sora-2, wan-25-preview)
is out of scope for a still-image Creative Director and omitted below):

| Endpoint | Reference images | Notes |
| --- | --- | --- |
| `POST /nano-banana` | `input_images` array, 0–8 | Confirmed `404 model_not_found` on this workspace. |
| `POST /higgsfield-ai/soul/standard` | none | No image input field at all — cannot ground a generation in real business assets. Previously probed: `403 not_enough_credits` (auth + model recognized). |
| `POST /higgsfield-ai/soul/character` | `image_reference_url` + required `custom_reference_id`/`custom_reference_strength` | Needs a pre-registered "custom reference" (character) id with no REST endpoint to create one in this spec — an out-of-band Higgsfield Cloud dependency, not self-sufficient via REST alone. |
| `POST /higgsfield-ai/soul/reference` | `image_reference_url`, exactly 1 (required) | **Selected candidate** — see below. |
| `POST /flux-pro/kontext/max/text-to-image` | none | Prompt-only in this REST schema (despite Flux Kontext's general image-editing reputation) — not usable for business-asset grounding. |
| `POST /reve/edit` | `image_url`, exactly 1 (required) | Single-image edit semantics (modifies one input), a different capability shape than "explore several directions from references." |
| `POST /reve/remix` | `image_urls` array, **2–4 required** (`minItems: 2`) | Rejected: a business with only one usable asset (e.g. logo only) cannot call this endpoint at all, and this workspace's entitlement for it is completely unverified (no historical signal either way). |
| `POST /reve/text-to-image` | none | Prompt-only. |

**Selected candidate: `higgsfield-ai/soul/reference`.** Rationale:

1. Same `higgsfield-ai/soul/` endpoint family as `soul/standard`, which
   this workspace's key was already confirmed (above) to recognize —
   `403 not_enough_credits`, not `404 model_not_found` — the strongest
   entitlement signal available *without* a real, billable call to this
   exact endpoint (Higgsfield's REST API exposes no models-list/
   entitlement-discovery endpoint of any kind — confirmed by enumerating
   every path in the spec; the only GET is `/requests/{id}/status`, which
   proves key validity, not per-model entitlement).
2. Accepts exactly one reference image, which fits a business that has at
   minimum a logo asset (never a hard multi-image minimum a thin asset
   library can't satisfy, unlike `reve/remix`).
3. No out-of-band setup dependency (unlike `soul/character`'s
   `custom_reference_id`).
4. `style_id` (a Higgsfield "Soul Style") is optional, not required — so
   this integration never needs to pre-select from a style catalog.

**This has NOT been confirmed against the real API** — Phase 2 of this
evaluation found no non-billable way to check a *specific* endpoint's
entitlement (see above: no models-list endpoint exists), and Higgsfield
documents no way to distinguish "not entitled" from "entitled, just out of
credits" without actually submitting to that exact endpoint. Switching
`HIGGSFIELD_API_MODEL` to `higgsfield-ai/soul/reference` in production
requires a real, potentially billable API call and operator approval
first — see the `hotfix/p2-higgsfield-model-fallback` PR for the exact
request proposed and its status.

## Internal fallback (P2.1 continuation)

`app.creative.director_fallback.FallbackCreativeDirector` now wraps
whichever Higgsfield director `app.dependencies.get_optional_higgsfield_director`
constructs (or `None`): a pre-acceptance failure (`HIGGSFIELD_API_MODEL`
unset/unrecognized, missing credentials, a 401, or the configured model
returning `404 model_not_found`) degrades that one `create_directions`
call to `InternalCreativeDirector` rather than failing the whole
workflow — tagged `provider_metadata = {"provider": "internal_fallback",
"fallback_reason": "higgsfield_model_unavailable" | "higgsfield_unavailable"
| "higgsfield_not_configured"}` so Studio and observability never imply a
Higgsfield-generated result came from Higgsfield when it didn't (P2.14).
A failure reached only by polling an *already-accepted* Higgsfield job
(insufficient credits, a timeout, `failed`/`nsfw`/`canceled`, or any
failure after at least one candidate already succeeded) is never eligible
for fallback — see that module's own docstring for the exact double-billing
argument.

**No cost-estimate endpoint exists in the REST API**, and no generation
response ever reports actual credits spent (confirmed against the same
OpenAPI spec — `RequestStatus`/`MediaOutput` carry no credit/cost field).
`HiggsfieldApiCreativeDirector` therefore uses a deliberately conservative,
*configured estimate* (`higgsfield_api_estimated_credits_per_call`, default
2.0) purely for `CreativeBudget.record_spend`'s pre-flight enforcement —
every `CreativeDirection.generation_metadata` this director produces
carries `"credits_are_estimated": true` so nothing downstream mistakes
this for a Higgsfield-confirmed figure.

## MCP (`https://mcp.higgsfield.ai/mcp`) — not production-suitable

Confirmed **not** used anywhere in this codebase, and not a viable
production path: an unauthenticated probe against that endpoint returns
`401` with `WWW-Authenticate: Bearer ... scope="openid email
offline_access"` — a standard OAuth Protected Resource challenge with
user-identity scopes, the same interactive-session shape as the CLI's own
`auth login`, just remote. Higgsfield's own documentation confirms this:
"MCP connects through OAuth authorization, no API key is needed."

## Required environment variables

Set these in `apps/api/.env` (never commit this file — it's already
git-ignored, same as every other credential in this project):

| Variable | Required for | Notes |
| --- | --- | --- |
| `HIGGSFIELD_API_KEY_ID` | The real P2 Creative Director (production) | Created in [Higgsfield Cloud](https://cloud.higgsfield.ai). Never logged. |
| `HIGGSFIELD_API_KEY_SECRET` | The real P2 Creative Director (production) | Same key pair as above. Never logged, never printed, never persisted anywhere but `.env`/the deployment's own secret store. |
| `HIGGSFIELD_API_KEY_NAME` | Nothing (optional) | Non-secret operator metadata — the key's display name in Higgsfield Cloud, for logging/capability reporting only. |
| `HIGGSFIELD_CLI_ENABLED` | Local dev / manual `real_provider` test only | Never set in production — see path 2 above. |
| `HIGGSFIELD_API_KEY` / `HIGGSFIELD_BASE_URL` | The unrelated legacy CreativeLevel PREMIUM/CINEMATIC path only | Do not confuse with the real P2.1 credential above. |

Both `HIGGSFIELD_API_KEY_ID`/`HIGGSFIELD_API_KEY_SECRET` must be set for
`get_optional_higgsfield_director` (`apps/api/app/dependencies.py`) to
construct a `HiggsfieldApiCreativeDirector`; either missing falls back to
`InternalCreativeDirector` (or the dev-only CLI path if
`HIGGSFIELD_CLI_ENABLED=true`) — never a silent, half-configured attempt.

## Persistent storage — artifacts AND business assets (P2.1, extended by
the persistent-business-assets-r2 hotfix)

See `app.storage.r2.CloudflareR2StorageProvider` and
`app.dependencies.get_storage_provider` — `R2_ACCOUNT_ID`/
`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/`R2_BUCKET_NAME`/
`R2_PUBLIC_BASE_URL` (all required together) switch production storage
from Railway's ephemeral local disk to persistent Cloudflare R2 for BOTH:

- generated artifacts (`GenerativeWebsiteArtifact` source archives,
  Visual QA screenshots), and
- real Studio business uploads (`app.routers.creative`'s
  `assets/upload`, `assets/upload-batch`, and `assets/{id}/replace` —
  logos, gallery photos), which record `storage_provider`/`storage_key`
  on the `BusinessAsset` row so a later caller can verify the object
  still exists (`app.services.asset_health`) or request a short-lived
  presigned reference for Higgsfield (`app.creative.higgsfield.director`)
  without guessing.

Leaving any of the five unset keeps `LocalStorageProvider` (dev/test
default) for both — in production, that means uploaded business photos
and logos do **not** survive a redeploy, which is the confirmed bug this
hotfix fixes.

## Adding these to `.env.example`

`apps/api/.env.example` lists the variable *names* only, never real
values — see that file directly for the current full list.

## Completing the integration further

Nano Banana Pro (or a future dedicated model), webhooks (instead of
polling), and a real cost-reporting endpoint are all plausible future
additions once/if Higgsfield documents them — add any such variable to
this table, `app.config.Settings`, and `.env.example` together, following
the same "no default, fail loud only when used" pattern already used for
every other optional provider in this codebase. Re-verify any new
endpoint path directly against `https://docs.higgsfield.ai/docs/openapi.json`
before using it — never guess a path.
