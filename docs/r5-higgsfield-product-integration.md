# R5 — Supervised Higgsfield exports in the real product workflow

R5 moves an owner-reviewed Higgsfield export through GWA's existing
product lifecycle:

```
Import ZIP -> immutable snapshot -> inspect -> classify -> AdaptationPlan
-> human review (if required) -> build on the worker -> trusted intake
(contracts + QA) -> immutable WebsiteArtifact -> real Preview -> Approve
(exact artifact) -> Publish (Build Once / Promote) -> Rollback
```

It is a SUPERVISED workflow: an operator uploads an export produced and
reviewed outside GWA. GWA never calls Higgsfield and Studio never offers
"generate with Higgsfield". Off by default
(`SUPERVISED_SOURCE_IMPORTS_ENABLED`, separate from the generative gate,
which stays off).

## 1. Audit: what R5 reuses (no duplicate systems)

| Existing path | Where | R5 use |
|---|---|---|
| Tenant/session auth + CSRF | `app.dependencies.get_current_tenant_id/get_current_user` | every R5 route; decisions record the user |
| Private storage (R2 private / local) | `app.storage.private.PrivateArtifactStorage` | snapshot, manifest, plan (identity-named, never overwritten) |
| Job queue + state machine | `app.creative.generation_jobs`, `GenerationJob` | new `job_kind`/`trust_class`/`plan_sha256` columns; same claim/lease/fail semantics |
| Worker protocol (pull, claim-only token, per-job HMAC token) | `app.worker.*`, `/internal/generation-worker/*` | `source_adaptation` jobs; job-token snapshot download |
| Trusted intake (headers re-derived, contracts, store, READY) | `app.worker.intake`, `drafts.judge_generative_candidate` | unchanged gates + source-specific identity/shape checks |
| WebsiteDraft lifecycle, write-once artifact identity | `app.db.models.website_draft` | the import's draft (GENERATIVE engine row + GenerativeWebsiteArtifact) |
| Real preview of the stored artifact | `drafts.ensure_draft_preview` | unchanged |
| Approve / publish (Build Once / Promote) | `drafts.approve_website_draft`, `publish_*`, `publishing.service.publish_prebuilt_artifact` | + approved-artifact binding + source gate |
| Versions / rollback (stored artifacts) | `publishing.versions.rollback_to_version` | unchanged |
| QA evidence bound to artifact | `publishing.qa_evidence` | approval requires current + passing evidence |
| PlatformContract / TruthContract | `app.qa.*` | unchanged, at intake |
| H2 adapter | `app.creative.source_adapter` | `inspect_export(allow_pending_review=True)` = the PROPOSED plan |

## 2. Lifecycle and states

`SourceImport.status` (inspection is synchronous and static): `blocked`,
`needs_review`, `rejected`, `ready_to_build`, `building`, `build_failed`,
`preview_ready`, `stale`. The draft carries the rest (`ready` ->
`approved` -> `published`). Studio shows one stage per import:
`blocked | stale | needs_review | rejected | ready_to_build | queued |
building | build_failed | preview_ready | approved | published` —
SOURCE REVIEW, BUILD/QA READY, ARTIFACT APPROVED and PUBLISHED are never
collapsed.

API (`/businesses/{id}/source-imports`): `capability`, `POST` (multipart
ZIP), list, detail (operator summary: identities, findings by kind,
security, BusinessTruth, origins, forms, build requirements, plan summary,
launch blockers, decisions, job, draft/QA/gate state), `diagnostics` (raw
manifest + plan, secondary), `decisions`, `reinspect`, `build`. Preview,
approve, publish, Visual QA and rollback are the existing draft/version
routes. Studio: `SupervisedImportPanel` (Brand & Content section).

## 3. Import and storage

Bounded upload (100 MB, a setting), ZIP magic + structure check, then the
H2 snapshot policy (no absolute paths, `..`, symlinks or special files,
entry count/size limits, exactly one `package.json`). Everything is
validated BEFORE anything is stored; a refused archive leaves nothing.
The snapshot is stored content-addressed
(`source-snapshots/{tenant}/{business}/{sha256}.zip`) and never
overwritten (an existing object must match byte for byte); manifest and
plan as `manifest-{sha}.json` / `plan-{sha}.json`. Nothing in the ZIP is
accepted as configuration: site origin and API origin come from trusted
server state.

## 4. Review model

A review decision (`source_review_decisions`, append-only) records finding
id, decision, rationale, actor (user id + email), timestamp, snapshot
SHA-256 and plan SHA-256. Only decisions bound to the import's CURRENT
snapshot and plan count. Blockers can never be approved. Every build,
approval and publish re-derives BusinessTruth: a change makes the import
`stale`; re-inspection yields a new plan identity, so earlier decisions
never carry over (the audit trail is kept).

R5 made `form_displays_server_identifier` a BLOCKER (a review finding in
H2): approving it cannot make the code work — the platform transport
returns no id, so the export no longer type-checks. Only a reviewed overlay
fix for that exact export resolves it. A changed Nexo export loses the Nexo
overlay (pinned to the original SHA-256) and is correctly blocked.

## 5. Build: worker architecture and boundaries

The API never builds an imported site. `build` queues a `source_adaptation`
job (`trust_class = supervised_source`). A worker claims it with its
claim-only credential and declared isolation and receives ONLY: job id and
attempt, business id, public API origin, site origin, source family, the
stored AdaptationPlan and identities. It downloads the snapshot with the
per-job token (one job, one attempt, short-lived), verifies the snapshot
and plan SHA-256, applies the exact plan (drift = stop), runs
`bun install --ignore-scripts` (no lifecycle hook runs at install), runs
the plan's BuildSpec steps, assembles the static artifact with the family
CSP, runs Visual QA (deterministic offline tier) and submits the
candidate. It never receives a database URL, an R2/Cloudflare/Resend/n8n/
provider/auth secret or BusinessConfig, runs no contract, and cannot
approve, publish or choose a destination.

Two worker isolation modes (`GWA_WORKER_ISOLATION`):

| Mode | Isolation | Jobs it receives |
|---|---|---|
| `bubblewrap` (default) | R4 sandbox: user/mount/PID/network namespaces, clean env, cgroup limits | any (AI-generated and supervised) |
| `supervised-process` | NOT a sandbox: separate process and session, allowlisted env, CPU/file-size/open-file limits, wall timeout; no filesystem/network/PID isolation, no memory or process-count limit (the container's) | `supervised_source` only |

The control plane routes by trust class (`next_queued_job_id`), refuses to
create a generative job with the supervised class, and rejects any
untrusted result not built by bubblewrap. The supervised tier exists
because Railway cannot create the R4 namespaces (R4.1 evidence); its
safety rests on owner review of the source, a worker that holds no platform
secret and no publish authority, and full re-validation by the control
plane. (RLIMIT_AS is deliberately not applied: Vite's Rolldown cannot
start its thread pool under it — found in the R5 E2E.)

## 6. Trusted intake (worker output is untrusted)

Job/attempt/token; candidate SHA-256, bounded link-free archive; `_headers`
byte-equal to the ones trusted code derives from the job's API origin and
family policy; untrusted jobs only from bubblewrap; for source jobs:
reported snapshot and plan identities equal the job's; the stored plan's
integrity; BusinessTruth unchanged since the plan; every planned page
present; no server/edge output (`server/`, `functions/`, `_worker.js`,
native binaries, executable magic); every page's platform config names
THIS job's business and API origin; then PlatformContract, TruthContract
and private storage (`judge_generative_candidate`), and Visual QA evidence
bound to the stored artifact and headers. Any failure: draft
`build_failed`, import `build_failed`, nothing stored, live site untouched.

## 7. Preview, approval, publish, rollback

Preview deploys the stored, SHA-verified artifact (never a rebuild) and
never changes approval. Approval of an imported draft requires: READY,
BusinessTruth unchanged, Visual QA evidence current for THIS artifact and
passing; it records `approved_artifact_sha256`. Publish requires
APPROVED, `approved_artifact_sha256 == artifact_sha256`, the same gate
again and the integrity-verified stored bytes (Build Once / Promote: no
rebuild, adaptation, header or metadata regeneration). A failed publish
leaves the live site and the approval unchanged. Rollback promotes a
stored version artifact without rebuilding.

## 8. Evidence (local; no provider, no deployment)

`scripts/r5_product_e2e.py`: real API (uvicorn), real login/CSRF,
throwaway SQLite, local private storage, a SEPARATE worker process
(`python -m app.worker --once`, minimal environment, no `.env`,
`supervised-process` mode), Chromium on the preview, the real Lead API;
Cloudflare substituted by local servers that serve exactly the artifact
they receive.

| | Nexo (real export, unchanged ZIP f3fbc3e7…) | Lumen (synthetic regression only) |
|---|---|---|
| Result | 33/33 | 30/30 |
| Import | SUPPORTED_WITH_REVIEW, 0 open (all resolved by adapter/overlay) | SUPPORTED_WITH_REVIEW, 0 open |
| Worker job (install + build + QA) | 19.4 s / 18.6 s | 8.8 s / 8.8 s |
| A -> published -> B -> published -> rollback | A `bdc049a5…`, B `09ce22bc…` (rebuild), restored A | A `2be98c70…`, B `92213fee…` (copy change), restored A |
| Changed export | copy edit -> no overlay -> `blocked` (server-id finding), build refused | copy edit -> built as B |

Nexo checks include all six videos from `blob:`, the Spanish consent
banner, legal routes, og:image/canonical/JSON-LD, no CSP violations, the
lead stored exactly once with every detail and visible through the Studio
leads API, preview = approved = published bytes, live serving the
published bytes, rollback bytes equal A.

`tests/test_r5_source_imports.py` runs ONE real build per module
(bubblewrap runner, real `bun` build and Visual QA) and replays the
genuine candidate, unchanged or tampered, through the API. See the test
names for the full failure matrix (archive policy, review gate,
staleness, snapshot integrity, worker boundary, intake rejections,
QA gates, publish/rollback failures).

## 9. Migrations and deployment ordering

`a7d3f1c5e8b2` (additive): `source_imports`, `source_review_decisions`;
`generation_jobs.job_kind/trust_class` (server defaults = existing
behaviour) and `plan_sha256`; `website_drafts.approved_artifact_sha256`.
Order: migrate, deploy the API (feature off), deploy a worker, then turn on
`SUPERVISED_SOURCE_IMPORTS_ENABLED`. A pre-R5 worker never builds a source
job (it only builds `gwa-astro` and fails closed).

## 10. Railway runtime requirements (estimate; no pricing, nothing provisioned)

Worker (a separate service/process from the API):
- toolchain: Python + this repo's app code (`uv sync --no-dev`), Node 24,
  bun 1.4.x, Playwright Chromium with its system libraries
  (`PLAYWRIGHT_BROWSERS_PATH`);
- process: `python -m app.worker` with `GWA_WORKER_ISOLATION=supervised-process`
  (Railway cannot run the bubblewrap mode), one job at a time;
- CPU/RAM: measured locally (`r5_product_e2e.py --measure`), a Nexo job
  takes ≈ 19 s and its largest single process peaks at ≈ 0.75–0.8 GB RSS
  (a LOWER bound: bun, Vite/Rolldown and Chromium run in sequence and in
  parallel within the job). Suggested starting point 2 vCPU / 2–4 GB RAM —
  to confirm against the container's own metrics on the first real run;
- storage: ephemeral only; per job ≈ the snapshot three times (zip,
  original, adapted) + node_modules (hundreds of MB) + the build; nothing
  persists between jobs except bun's cache in the worker's HOME;
- network: outbound HTTPS to the API origin and registry.npmjs.org (the
  trusted install); no inbound port; it must NOT sit on a private network
  that reaches Postgres or other internal services;
- secrets: ONLY the worker claim token (`GWA_WORKER_TOKEN`) and
  `GWA_API_BASE_URL`. No shared variables from the API service.

API: `GENERATION_WORKER_TOKEN_SHA256`, `GENERATION_WORKER_SIGNING_KEY`,
`SUPERVISED_SOURCE_IMPORTS_ENABLED=true`, the existing private R2 bucket,
and request bodies up to the upload limit through Railway's proxy (to
verify).

## 11. What still prevents a safe deployment

- **Technical deployment blocker:** no worker exists. Railway cannot run
  the R4 sandbox, so a Railway worker would be the `supervised-process`
  tier — acceptable only for owner-reviewed sources and only if the
  service is isolated from the API's private network and variables. Its
  creation, sizing and network isolation are owner decisions (not done).
  Total peak memory under the container and the proxy's upload limit are
  unverified.
- **First pilot/customer input:** real BusinessTruth (legal identity,
  contact, logo), owner review of claims and favicon, a reviewed overlay
  for that customer's export, a domain.
- **Legal/owner input:** legal name, NIF, registered address, privacy
  contact, legal text review.
- **External Higgsfield automation:** no documented API/MCP/CLI to
  generate or export; exports remain manual and supervised.
