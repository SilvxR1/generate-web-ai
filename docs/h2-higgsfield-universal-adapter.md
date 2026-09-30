# H2 — Higgsfield universal (family) source adapter

H2 turns the Nexo-specific H1/H1.2 integration into a reusable, deterministic,
fail-closed pipeline. It is NOT automated Higgsfield generation and NOT a
deployment: a *supervised* export enters as immutable source and leaves as a
validated, immutable GWA `WebsiteArtifact`.

```
export ZIP
 -> snapshot_export        immutable original (read-only, hash-identified)
 -> inspect_source         SourceManifest (static; nothing executed)
 -> select_adapter         exactly one source-family adapter
 -> map_form / discover_facts / reconcile_claims
 -> classify               SUPPORTED | SUPPORTED_WITH_REVIEW | UNSUPPORTED
                           (STOP, nothing mutated, unless every finding is
                           resolved or approved)
 -> plan                   AdaptationPlan: dry-run on an in-memory copy
 -> apply_plan             same operations on the working copy; drift = stop
 -> bun install --ignore-scripts (trusted) -> BuildSpec steps (R4 sandbox)
 -> assemble_static_artifact -> PlatformContract + TruthContract -> artifact
```

Higgsfield stays the creative authority (layout, CSS, animation, media, copy
are the export's); GWA stays the platform authority (lead transport, consent,
legal, SEO, CSP, asset policy, BusinessTruth, contracts, QA evidence).

## Generic platform vs source-specific adaptation

| Concern | Where | Kind |
|---|---|---|
| Immutable snapshot, manifest, classification, plan/apply, artifact, contracts, QA evidence | `snapshot.py`, `manifest.py`, `classify.py`, `plan.py`, `pipeline.py` | generic |
| Platform SDK, lead transport module, consent theme, legal content/pages/routes, business module + JSON-LD, OG image, readiness | `platform_files.py` | generic (React family) |
| Form discovery + FormMapping, BusinessTruth discovery + claims | `forms.py`, `facts.py` | generic |
| Framework/build/prerender, server-function transports, head/fonts, app-meta, brand policy, host hooks | `adapters/higgsfield_tanstack.py` | **family** (`higgsfield-tanstack-static`) |
| Decisions not inferable from source (banner theme, legal-link placement, share frame, approved fixes, claims to confirm) | `overlays/<export>.py` | **one export**, pinned to its snapshot SHA-256, reviewed data |

There is no business- or export-conditional platform code. An overlay is
selected only by the snapshot's SHA-256 (`overlays.overlay_for`); a different
export — even one byte different — gets none and is adapted by the family
adapter alone (the synthetic fixture has no overlay).

## Adapter contract (`adapters/base.py`, `ADAPTER_CONTRACT_VERSION = 1.0.0`)

```
detect(manifest) -> bool
assess(manifest, tree, overlay) -> [Finding]          family supportability
resolve(finding, manifest, tree) -> str | None        what the family handles, how
csp_requirements(manifest, tree) -> CspExtensions     validated vs the family policy
locale(manifest, tree) -> "es" | "en"
text_paths(manifest, tree) -> [path]                  where visitor text lives
build_spec(manifest, pages) -> BuildSpec              install, sandbox steps, output, expected pages
plan(PlanContext, PlanBuilder) -> pages               operations (dry run)
```

`higgsfield-tanstack-static@1.0.0` is the first implementation; Nexo is its
reference export.

## SourceManifest (`MANIFEST_VERSION = 1.0.0`)

Computed from bytes only (package.json, lockfile, import graph, lexical scan of
TS/TSX/JS via `tsx_scan.py`, CSS text, magic bytes); sorted, no timestamps, no
absolute paths, external URLs by ORIGIN only. `manifest_sha256` is its
identity and it embeds `snapshot.zip_sha256`.

Fields: `snapshot`, `framework` (deps, router, TS), `package_manager`
(lockfile + SHA), `build` (command, scripts, expanded steps), `dependencies`
(name/spec/section/kind), `modules` (live set, unavailable builder packages,
design-critical, removable), `routes` (path/kind/dynamic/live/head), `forms`
(fields, labels, options, transport, honeypot), `navigation`, `images`,
`videos` (SHA + referencing modules), `fonts` (family/provider/weights/
delivery), `brand_assets`, `external_origins` (origin, context:
stylesheet/preconnect/font/script/connect/media/link/reference, files,
client-live), `analytics`, `host_hooks`, `metadata` (app-meta keys, external
origins, head modules), `structured_data`, `claims`, `integration_points`,
`security`, `already_adapted`.

Nexo (`nexo-reformas-web.zip`, 223 files): TanStack Start 1.168 / React 19 /
Vite 8 / Tailwind 4, bun; build `check:ui && tsr generate && tsc --noEmit &&
vite build`; 24 live modules (42 removable: 4 unavailable `@higgsfield/*`
workspace packages); routes `/` (+ `/app` dead, 2 server routes); 1 live form
(6 fields, server-function transport, displays the server id); 31 images,
12 videos; fonts Inter Tight + IBM Plex Mono (Google), Cabinet Grotesk
(Fontshare); client origins: Fontshare, Google Fonts (2), the Higgsfield CDN
(page metadata only); security: 1 lifecycle script (`postinstall: node
scripts/verify-install.mjs`), 2 server-runtime modules; host hooks: the
Higgsfield error-reporting global and its design inspector; 0 claims, 0
analytics, 0 secrets.

## Supportability (`classify.py`)

Findings are `blocker | review | info`, id `<code>:<subject>`. A finding is
RESOLVED only by a named family/overlay action (the resolution text says
which; an overlay resolution must be backed by one of its patches — checked
at load) or, for REVIEW findings only, APPROVED by a human in the overlay.
Blockers are never approvable.

Generic rules: `no_family_adapter`, `already_adapted`,
`design_critical_dependency`, `non_registry_dependency`, `secret_like_string`
(known formats: blocker; generic assignments: review; values never
recorded), `environment_file`, `npmrc`, `trusted_dependencies`,
`binary_executable` (wasm: review), `remote_script`, `no_build_command`,
`network_origin_not_permitted` (a client-live fetch outside the family CSP
policy) — blockers; `lifecycle_script`, `dynamic_code`, `raw_html_injection`,
`process_env_access`, `unscannable_module`, `server_runtime`, `host_hook`,
`analytics_or_tracking`, `source_structured_data`, `no_lockfile` — review;
`external_link` — info.

Family rules (`higgsfield-tanstack-static`): `package_manager_unsupported`,
`no_static_build`, `dynamic_route_not_prerenderable`, `legal_route_conflict`,
`build_config_unrecognized`, `prerender_already_configured`,
`root_document_unrecognized`, `index_route_unrecognized`,
`index_head_unsupported`, `font_not_self_hostable`,
`form_transport_imports_more`, `server_module_still_imported` — blockers;
`build_step_unrecognized`, `no_lead_form`, `form_displays_server_identifier`,
`legal_links_placement` — review; `third_party_font_service`,
`generated_brand_mark` — info. Forms/facts/claims add
`form_without_contact_field`, `form_transport_unmappable`,
`form_detail_keys_collide`, `form_too_many_details`,
`service_not_in_business_truth`, `unverified_contact_claim` (blockers) and
`form_role_ambiguous`, `form_field_dynamic_name`,
`form_required_field_unrecognized`, `service_written_differently`,
`unverified_factual_claim` (review).

## AdaptationPlan (`plan.py`, `PLAN_VERSION = 1.0.0`, platform integration 2.0.0)

Built by dry-running each operation on a `VirtualTree` copy. Four mechanical
actions — `add` (never overwrites), `remove`, `replace` (exact-once),
`json` (top-level keys, with expectations) — each recorded with `op_id`,
`category` (cleanup, platform-sdk, lead-transport, consent, legal, seo,
assets, fonts, brand, business-truth, build, approved-fix), `reason`,
`origin` (family adapter@version or overlay), visitor-visible effect, and
before/after SHA-256. Structural transformations (import rewiring, JSX
insertion, prerender config, fact binding) are located with `tsx_scan` and
expressed as `replace` of the smallest unique whole-line window
(`edits.py`), so the plan is a reviewable diff.

The plan also records: adapter/overlay identity, snapshot + manifest +
BusinessTruth SHA-256, site origin/locale, the full supportability report,
form mappings, fact bindings + ledger, CSP (requested by the source and the
family policy applied), BuildSpec, approvals/resolutions, readiness
findings, source and predicted adapted tree SHA-256 — and `plan_sha256`
over all of it.

`apply_plan` refuses (PlanDriftError) when the working copy is not the tree
the plan started from, when any file differs from an operation's
before-SHA, or when a result differs from its after-SHA — so a plan can
never be applied twice, to another source, or partially.

## BusinessTruth (`facts.py`)

Facts are discovered, not assumed: visitor-readable text only (string
literals outside machine attributes/keys, and JSX text); scalars (name, city,
country name) as whole words; services as whole values by name or by id
slug (so a renamed service still binds to its id); SERVICE COLLECTIONS
(arrays presenting >= 2 truth services under one key) expose every service
the export presents — one missing from BusinessTruth is a blocker, except a
catch-all option. Bindings replace literals only when the truth value
differs (the plan records the others). The FACT LEDGER records which
literal each fact was found as; a later plan given the ledger binds a
changed fact where the export wrote it (without it, a changed scalar is
reported as `truth_fact_not_presented`, never guessed). Claims (prices,
ratings, reviews, years, counts, certifications, awards, guarantees,
percentages, addresses, contacts) are detected truth-independently and
reconciled: unknown contacts block; other hard claims need owner
confirmation. JSON-LD is built only from BusinessTruth.

## Forms (`forms.py`)

Discovery reads each `<form>`'s fields (name, element, type, required,
autocomplete, label from a wrapper `label=` prop / `<label htmlFor>` /
aria-label, static options) and its transport. Mapping gives every field a
role — name, email, phone, message, service, consent, detail — from its
semantics (type, autocomplete, multilingual name hints, options matching
BusinessTruth services), in any order and with any names. Non-core fields
are kept as labelled details (no data loss). The family rewires a
`serverFn({ data })` transport to a generated module with the same call
shape: it reads the form's own fields, sends core fields + details through
the SDK, reuses the submission id across retries, carries honeypot + timing,
and throws on failure so the form's own error state shows. The form's code,
validation and states are unchanged.

## Results

| | Nexo (real export) | lumen-physio (SYNTHETIC) |
|---|---|---|
| Classification | SUPPORTED_WITH_REVIEW, 0 open (4 blockers + 6 reviews all resolved; 1 via overlay) | SUPPORTED_WITH_REVIEW, 0 open (3 blockers + 2 reviews resolved by the family) |
| Plan | 84 operations (81 family, 3 overlay), 66 files | 30 operations (all family), 20 files |
| Build | postinstall check + `bun run build`, R4 bubblewrap | `bun run build`, R4 bubblewrap |
| Pages | `/`, `/privacy`, `/terms`, `/cookies` | `/`, `/studio`, `/privacy`, `/terms`, `/cookies` |
| PlatformContract 1.1.0 / TruthContract 1.0.0 | 0 / 0 findings | 0 / 0 findings |
| End-to-end QA (real local API) | 52/52 | 49/49 |
| Visual vs accepted H1.2 baseline | 20/20 screenshots 0.0 % changed | n/a (no prior baseline) |

The synthetic fixture (`apps/api/tests/fixtures/higgsfield_synthetic/
lumen-physio`) differs from Nexo in file organisation (`src/features`,
`src/content`, `src/server`, app at the ZIP root), form (7 differently named
fields in another order, consent checkbox, static options, result unused),
content placement (a data module), assets (`public/media`, `public/brand`
SVG logo), navigation (two page routes + anchors), CSS (plain CSS, no
Tailwind), fonts (Fraunces + Inter), language (English) and Vite config
shape. **It is synthetic: it proves the adapter is not Nexo renamed, not that
future Higgsfield exports will conform.**

## Determinism and idempotency

For the same snapshot + BusinessTruth + adapter version + platform
integration version, two independent runs produce the identical
SourceManifest, AdaptationPlan (`plan_sha256`) and adapted source tree
(`adapted_tree_sha256`) — verified for both fixtures, and by the unit tests.
The BUILT artifact differs between two builds only by TanStack Start's
prerender timestamps (the router's dehydrated `updatedAt`, `u:<ms>`, 8
occurrences in Nexo's HTML) and the inline-script CSP hashes derived from
them: normalizing those timestamps makes all 125 files of two Nexo builds
identical. This is unavoidable build metadata; Build Once / Promote means
the one built artifact's SHA-256 is the identity that is QA'd and promoted.

Idempotency: a plan applies once (`apply_plan` refuses any file that is not
what the plan saw, so nothing — SDK import, consent theme, legal routes,
metadata, form wiring, platform files — can be added twice); an adapted
source is refused by inspection (`already_adapted`); adaptation always starts
from the immutable snapshot.

## Security coverage and limits

Detected statically and reported: secret-shaped strings (never recorded),
environment files, `.npmrc`, install lifecycle scripts (never run: install
uses `--ignore-scripts`; only `node scripts/*.mjs` postinstall checks run,
inside the no-network sandbox), `trustedDependencies`, executables/binaries
(magic bytes + suffixes), remote script injection, `eval`/`new Function`,
`dangerouslySetInnerHTML`, client `process.env`, server runtime
(`createServerFn`, `cloudflare:*`), known trackers, network origins by
context. The CSP is never widened: a source's needs are validated against
the H1.1 family policy (fail closed), and the artifact headers are the
family policy (intake re-derives the same). The export's code only executes
inside the R4 sandbox, never in the API process.

This is inspection, not a malware scanner or a security audit: patterns catch
obvious cases; obfuscated code, a malicious dependency on the registry or
novel exfiltration would not necessarily be detected. The sandbox (no
network, cleared env, limits) remains the control that contains execution.
`tsx_scan` is a conservative lexer, not a parser: misread constructs fail
closed (exact-once edits + the export's own tsc/vite build).

## Remaining blockers

- **Railway/build integration:** the execution host builds only `gwa-astro`;
  the H2 pipeline (bun toolchain, the adapter, per-family prepared
  dependencies, source snapshots as job inputs) must run on the worker;
  per-source CSP tightening needs intake to carry the requested subset.
- **First real customer/pilot:** a real business's BusinessTruth (legal
  identity, contact, logo), owner confirmation of claims and icons, legal
  review, a reviewed overlay for its export, a real domain.
- **External Higgsfield automation/API:** no documented API/MCP/CLI for
  Supercomputer generation or export; exports are manual. Only one real export
  exists, so family coverage of other Higgsfield templates is unproven.
- **Owner/legal input:** legal name, NIF, registered address, privacy contact,
  legal text review, favicon approval, the listed claims.

## Reproduce

```
uv run python scripts/h2_source_adapter.py --fixture nexo-reformas --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-h2/nexo
uv run python scripts/h2_e2e_qa.py --fixture nexo-reformas --work-root /tmp/gwa-h2/nexo \
    --offsets /path/spike/visual/report.json --baseline /path/h1.2/qa
uv run python scripts/h2_source_adapter.py --fixture lumen-physio --work-root /tmp/gwa-h2/lumen
uv run python scripts/h2_e2e_qa.py --fixture lumen-physio --work-root /tmp/gwa-h2/lumen
# --plan-only: inspection, classification and plan only (no install/build)
```
