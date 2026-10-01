# R5.1 — Railway build worker: deployment-readiness and specification

R5.1 makes the supervised build worker deployable. This document
specifies the Railway service that would be created after approval. It
does not create it: no service exists, no Railway variable was changed, and
`SUPERVISED_SOURCE_IMPORTS_ENABLED` stays off.

**Trust model.** The worker accepts only owner- or operator-reviewed,
supervised Higgsfield exports. It does not accept arbitrary customer code
or arbitrary internet source code.

Railway's supervised-process mode is **not a security sandbox**. It
provides no filesystem, network, PID or memory isolation, because Railway
cannot create the R4 user namespaces. The worker is instead built for
least privilege:

- it holds no platform credential;
- it has no publish or approve authority;
- every child process gets an explicit environment;
- the control plane re-validates every byte the worker returns.

## 1. Service specification (to create later)

| | |
|---|---|
| Purpose | Build owner-reviewed Higgsfield exports (R5 `source_adaptation` jobs). Nothing else. |
| Source | This repository, branch `main`. |
| Build | Dockerfile `apps/api/Dockerfile.worker`, built from the monorepo root. Config-as-code: `apps/api/railway.worker.json`. Set that path as the service's config file; the API keeps the root `railway.json`. |
| Start command | The image entrypoint, `python -m app.worker` (service loop). Do not override it. |
| Replicas | 1. Each process runs one build at a time (`GWA_WORKER_CONCURRENCY=1`, the only accepted value). Scale by adding replicas only after measuring. |
| Public domain | None. The worker needs no inbound traffic; the health port is for Railway's deploy healthcheck only. |
| Private networking | It must not use the project's private network to reach Postgres or Redis. Its only peer is the API's public `https://` origin. |
| Restart | `ON_FAILURE`, max 5 retries. Exit 78 means misconfigured (preflight failed); retries will not fix it, so the deploy fails visibly. |
| Draining | `drainingSeconds: 30`. On SIGTERM, a building worker kills its build, removes its workspace, releases the attempt (the job is requeued) and exits in under 1 s (measured 0.3–0.6 s). |
| Health | `GET /health` on `$PORT`. It returns 200 only after the preflight passed and while the loop is alive, and 503 otherwise. A misconfigured worker exits before serving, so a deploy can never be marked healthy by a bad worker. |

### Variables

**Required:**

| Name | Value |
|---|---|
| `GWA_API_BASE_URL` | The API's public `https://` origin. No credentials, query or fragment; plain `http` is only accepted for loopback, in local tests. |
| `GWA_WORKER_TOKEN` | A new random token of at least 32 characters, used only by the worker. The API stores only its SHA-256 (`GENERATION_WORKER_TOKEN_SHA256`). |
| `PORT` | e.g. `8080`, for the deploy healthcheck. |

**Optional:**

| Name | Use |
|---|---|
| `GWA_WORKER_ID` | Name shown in logs. |
| `GWA_WORKER_WORK_ROOT` | Default `/tmp/gwa-worker`. |

The image already sets `GWA_WORKER_ISOLATION=supervised-process`,
`GWA_WORKER_CONCURRENCY=1` and `PLAYWRIGHT_BROWSERS_PATH`.

**Forbidden.** The worker refuses to start (exit 78) if any of these is
present. Only the variable name is reported, never its value.

- Every API-only setting, derived from `app.config.Settings`: `DATABASE_*`, `CREDENTIAL_*`, `N8N_*`, `ANTHROPIC_*`, `GENERATION_WORKER_*` (the API's signing key and token hash), `INTERNAL_AUTOMATION_*`, `CLOUDFLARE_*`, `SMTP_*`, `RESEND_*`, `HIGGSFIELD_*`, `GOOGLE_REVIEWS_*`, `R2_*` and `ALERT_WEBHOOK_*`.
- Platform names: `DATABASE_PUBLIC_URL`, `DATABASE_PRIVATE_URL`, `PG*`, `POSTGRES_*`, `REDIS_URL`, `OPENAI_API_KEY`, `CF_*`, `AWS_*`, `RAILWAY_TOKEN`, `RAILWAY_API_TOKEN`, `GITHUB_TOKEN`, `GH_TOKEN`, `NPM_TOKEN`, `NODE_AUTH_TOKEN` and `PUBLIC_API_BASE_URL`.
- Any credential-shaped name (`*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_KEY`, `*_API_KEY`, `*_ACCESS_KEY`, `*_CREDENTIALS`) other than `GWA_WORKER_TOKEN`.
- Any value shaped like a URL with an embedded password.

Do not attach Railway shared variables or a database reference to this
service.

**API side** (when enabling; not now): `GENERATION_WORKER_TOKEN_SHA256`
(the SHA-256 of the worker token) and `GENERATION_WORKER_SIGNING_KEY` (a
new random key, API only).

### How to verify the worker has no credentials

1. Railway dashboard → service → Variables: only the three variables above (plus Railway's own non-secret `RAILWAY_*` metadata).
2. Deploy logs: the first line is `preflight passed {...}`, including `"no_platform_credentials": ok`. If anything is inherited, the log names it and the deploy fails.
3. On demand, run `python -m app.worker --preflight` in the service shell. It prints the JSON report, which contains names only.

## 2. Container and toolchain

`apps/api/Dockerfile.worker`, base images pinned by digest:

| Component | Version |
|---|---|
| Python | 3.12.12 (`ghcr.io/astral-sh/uv:python3.12-bookworm-slim`), with dependencies from the API's `uv.lock` (`uv sync --frozen --no-dev`) |
| Node | v24.19.0 (binary from `node:24.19.0-bookworm-slim`; no npm, npx or corepack) |
| bun | 1.4.2 (binary from `oven/bun:1.4.2-debian`) |
| Chromium | headless shell 151.0.7922.34 (Playwright 1.62.0 `--only-shell`, system libraries via `--with-deps`) |

- **Contents:** only `apps/api/app` plus the locked Python dependencies. No tests, scripts, migrations, `.env` or JS workspace.
- **Runtime privileges:** runs as uid 10001 `gwa`. No bubblewrap, no Docker-in-Docker and no privileged requirement. It runs with `--cap-drop ALL --security-opt no-new-privileges` in the local tests.
- **Size:** 505 MB uncompressed. The image builds in about 50 s from cold layers.
- **`GPG_KEY`:** the base image's public Python release-key id is blanked in the image, so the credential-name denylist has nothing to flag. It is not a secret.

## 3. Startup preflight (`app/worker/preflight.py`)

The worker checks all of the following before it claims anything; any
failure means exit 78 and no claim.

- No platform credential is present (the denylist above).
- `GWA_API_BASE_URL` is valid.
- The token is present and at least 32 characters.
- The isolation mode is valid.
- Concurrency is 1.
- Python is 3.12 or later.
- Node major version is 24.
- bun is 1.4 or later.
- Chromium actually launches, with a minimal environment.
- The workspace is writable with at least 2 GiB free.
- There is no `.env` in the working directory.
- Any visible container memory limit is at least 2 GiB.

The app version and Railway commit are reported as facts. After passing,
the worker removes the token and API URL from its own environment.
Forbidden variables are re-checked before every claim.

## 4. Child-process environment

| Process | Environment |
|---|---|
| `bun install` | Built from scratch: `PATH`, `HOME`/`TMPDIR` (private, in the job workspace), `BUN_INSTALL_CACHE_DIR` (same), `NO_COLOR`, `DO_NOT_TRACK`, `LANG`. |
| Build steps (`bun run …`, Vite/Rolldown, the export's own scripts) | `PATH`, `LANG`, `NO_COLOR`, `DO_NOT_TRACK`, `CI`, plus a private per-step `HOME`/`TMPDIR` that is removed after the step. The runner refuses any `GWA_*` or credential-shaped name. |
| Chromium (Visual QA) | `PATH`, `HOME`, `TMPDIR`, `LANG`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, all private. |
| Playwright driver | Inherits the worker's own environment, which by then no longer has the token or API URL. |

**Measured inside the real container.** The Lumen export's own
`vite.config.ts` reported its full environment:
`CI, DO_NOT_TRACK, HOME, LANG, NODE, NODE_ENV, NO_COLOR, PATH, PWD, SHLVL, TMPDIR, _`
plus the `npm_*` variables bun itself adds. It contained no `GWA_*`
variable, no credential name and no 64-hex value. The pytest suite proves
the same for a real Vite build with a token and secrets planted in the
worker's environment, and for the real Chromium processes, read via
`/proc/<pid>/environ`.

## 5. Network

| Traffic | Destination | Needed for |
|---|---|---|
| A. Control plane | `GWA_API_BASE_URL` over HTTPS (claim, snapshot download with the job token, result) | Every job |
| B. Dependency install | `registry.npmjs.org` over HTTPS | `bun install --ignore-scripts` |
| C. Visual QA | None. Chromium loads the artifact from a loopback server, and every non-local request is answered offline or aborted (offline tier). | — |

**Observed.** I ran the real Nexo job in the container with a logging DNS
resolver (`scripts/r5_1_dns_audit.py`, a test harness only). The only
name resolved, across both builds, was `registry.npmjs.org`. The local
API was reached by IP. Connections to literal IPs would not show in that
log.

H2/R5 already guarantee there is no other registry:

- `.npmrc` is refused;
- `bunfig.toml` is limited to an allowlist;
- only plain registry semver specs are accepted;
- every lock entry must come from the default registry.

**Enforcement.** Railway cannot restrict egress per service. The worker
therefore can reach the internet (supervised mode has no network
isolation). Mitigations:

- it holds nothing worth exfiltrating except its own claim token;
- the source has been reviewed by a human;
- the control plane trusts nothing it returns.

If egress control becomes a requirement, it needs infrastructure Railway
does not offer (out of scope).

## 6. Dependency install

- `bun install --ignore-scripts`: no dependency lifecycle hook runs at install.
  - The plan's own BuildSpec steps run afterwards, as reviewed. Nexo's `postinstall` check runs that way.
  - `trustedDependencies` is refused.
- **Lockfile authority (new in R5.1):** after install, every resolved `name@version` + integrity must already be pinned by the export's own `bun.lock`.
  - Pruning is allowed, including bun re-hoisting a pinned version to another key.
  - So are the plan's own exact-version additions (self-hosted `@fontsource` packages).
  - Anything else fails the build ("changed the reviewed lockfile").
- The H2 supportability result stays authoritative. A blocked or stale import is never queued (R5 tests).
- **Snapshot integrity:**
  - The immutable snapshot lives in private storage, which the worker cannot write; it holds no storage credential.
  - Inside the job, the extracted original is digested before and after install/build. A change refuses the result.
  - The downloaded ZIP is re-hashed.
- **Not protected:** a malicious package *already pinned* in a reviewed lockfile would run during the build. That is why only owner-reviewed exports are accepted.

## 7. Workspace lifecycle

- **One directory per job:** `$GWA_WORKER_WORK_ROOT/job-<id>-<attempt>-<rand>`.
  - Python's `tempfile.tempdir` and `TMPDIR` point there for the whole job.
  - It holds the source ZIP, the extracted original, the adapted tree, `node_modules`, the bun home, the step homes, the build output and the Playwright/Chromium profile.
- **Removed every time:** on success, failure, an unexpected exception, timeout or SIGTERM (tests and container `docker diff`).
- **SIGKILL leftovers:** a SIGKILL'd worker leaves its directory. The next process empties the whole work root at start, and a Railway restart starts from a fresh container filesystem.
- **No persistent disk; no dependency cache across jobs:** each job's bun cache lives in its workspace. This is deliberate, for tenant separation; a cache is an optimisation for later.

## 8. Resource controls and limitations

**Enforced:**

- Job deadline: 12 min, inside the 15-min lease. Install and build steps get at most the time left.
- Install timeout: 300 s.
- Per-step wall timeout: 600 s.
- `RLIMIT_CPU` (1200 s per process), `RLIMIT_FSIZE` (256 MiB per file) and `RLIMIT_NOFILE`.
- Process-group kill on timeout or shutdown, with any orphaned descendants killed after each step.
- Snapshot ≤ 100 MB, at most 5000 entries, ≤ 64 MiB per file and ≤ 512 MiB extracted.
- Candidate archive and screenshots are bounded by the protocol.

**Not enforced (stated plainly):**

- memory: `RLIMIT_AS` breaks Rolldown, so the only bound is the container's memory limit;
- process count;
- `/tmp` size;
- filesystem, network and PID isolation.

**Telemetry** goes to the existing logs only: one `source-adaptation job
metrics` line per job (duration, source bytes and files, artifact bytes
and files, peak RSS of the build process tree via `wait4`, status and
failure category). The same values are in the result metadata.

## 9. Worker token (unchanged design, now tested end to end)

- **Claim-only.** The worker token can only `POST /internal/generation-worker/claim`, and only receives jobs its isolation may run.
- **Job token per claim.** Each claim issues an HMAC job token bound to one job and one attempt, valid 20 min. It can only download that job's snapshot while RUNNING and submit that attempt's result once.
- **Refused everywhere else** (tests and container checks), as bearer or as a session cookie:
  - Studio/operator routes: source imports, build, approve, publish, preview, leads and the business list;
  - the snapshot endpoint, when presented as the worker token;
  - another job's snapshot (with a job token);
  - claiming (with a job token);
  - a finished job.
- **No publish surface:** the worker router has exactly three routes (claim, source, result).

No token was created or rotated.

## 10. Crash, lease and retry

| Event | Behaviour |
|---|---|
| SIGTERM during download, install, build or QA | The build tree is killed, the workspace removed, and `WORKER_LOST` is reported for this attempt. The control plane requeues the source job, the next claim is attempt 2, and the worker exits 0. |
| SIGKILL or crash at any point | The job stays RUNNING until its 15-min lease expires. The next claim requeues it, and the claim then runs attempt 2. |
| Crash while submitting | The result was either accepted, or the lease expires and the job is retried. A second submission of the same attempt gets a 409. |
| Late result from a lost attempt | 401: its token is bound to the old attempt. |
| Requeue limit | 3 claims per source job (`MAX_SOURCE_ATTEMPTS`). Then the job fails as `WORKER_LOST`, the import shows `build_failed` (never stuck in `building`), and the operator can rebuild. |
| Generative (AI) jobs | Unchanged: never retried automatically. |

**Real container results (Lumen):**

- SIGTERM mid-build: released, then finished as attempt 2.
- SIGKILL mid-build: the lease passed, then finished as attempt 2.
- Exactly one stored artifact each time.

R5.1 also fixed an R5 defect: lease expiry used to leave the source import
in `building` forever.

Lease expiry is evaluated when a worker claims. If no worker ever claims
again, a RUNNING job stays RUNNING, but then nothing builds at all.

## 11. Concurrency

One build per worker process, by construction: claim → execute → report,
then the next claim. A second queued job stays queued. A test verifies
that the loop never has two jobs in flight and that claims are strictly
sequential. `GWA_WORKER_CONCURRENCY` must be `1`; any other value fails
preflight. With about 20 s and about 0.85 GiB per Nexo build, one process
per replica is the launch setting.

## 12. Evidence (local, real image, no provider or deployment)

| Run | Result |
|---|---|
| Nexo full product E2E, worker in the container, DNS audit on (`r5_product_e2e.py --worker-image … --dns-audit`; two full runs, four builds) | **33/33** both times. Each job took 19.6–20.8 s, including install, build and Chromium QA. Peak RSS of the build process tree was 0.73–0.76 GiB; the container peaked at 766–857 MiB (Docker stats, 0.5 s sampling). Source 30.4 MB / 225 files; artifact 31.8 MB / 125 files. DNS: `registry.npmjs.org` only. |
| Lumen regression, default entrypoint (non-root, `--cap-drop ALL`, no-new-privileges) | **30/30**. About 8.5 s per build; container peak 409–511 MiB; artifact 1.04 MB / 59 files. |
| Container checks (`r5_1_container_checks.py`) | **24/24**: startup refusals, health, environment probe, SIGTERM/SIGKILL recovery, token authority and upload limits. |

**Suggested starting size:** 2 vCPU and 2 GiB RAM, or 4 GiB for headroom
on larger exports. Confirm against Railway's own metrics on the first
real job. No pricing is implied.

## 13. Upload path and limit

- **Path.** Studio calls the API origin directly (`VITE_API_URL`). There is no proxy of ours in between, only Railway's edge.
- **Railway's documented limits:** no request-body size limit; the upload must complete within 5 minutes; 32 KB of headers. See [Railway specs & limits](https://docs.railway.com/networking/public-networking/specs-and-limits).
  - A 100 MB ZIP therefore needs about 2.7 Mbit/s of sustained upstream from the operator.
  - Inspection then runs inside the same request; Nexo, about 30 MB, takes a few seconds.
- **App limit:** unchanged at 100 MB.
  - **New in R5.1:** `SourceUploadLimitMiddleware` answers 413 from the `Content-Length` before the body is received. Starlette would otherwise spool the whole multipart body to disk before the route's own check.
- **Local proof over real HTTP:**
  - a valid 98.7 MB ZIP was accepted and inspected (201, 2.1 s on loopback);
  - a declared over-limit body was refused in under 0.1 s without being read.
- **Deployment validation item:** confirm the 5-minute window with a real operator connection, using a non-production business on a staging deployment if one exists. This was not tested against production.

## 14. Future enablement runbook (NOT executed)

1. **API compatible.** Main already contains R5 (migration `a7d3f1c5e8b2`, applied). Merge R5.1 when approved. Imports stay OFF.
2. **Generate the credentials** outside the chat:
   - a worker token (`openssl rand -hex 32`), stored only as the worker's `GWA_WORKER_TOKEN`;
   - its SHA-256, as the API's `GENERATION_WORKER_TOKEN_SHA256`;
   - a new `GENERATION_WORKER_SIGNING_KEY` on the API.
   - Redeploy the API. Imports stay OFF.
3. **Create the worker service** from `apps/api/railway.worker.json`:
   - variables `GWA_API_BASE_URL`, `GWA_WORKER_TOKEN` and `PORT`;
   - no shared variables, no database reference, no public domain.
4. **Verify the worker:**
   - the deploy is healthy;
   - the log shows `preflight passed` with `no_platform_credentials` ok;
   - the Variables tab holds only the three variables;
   - `python -m app.worker --preflight` reports ready.
5. **Safe test job (R5.1.1 scoped access).** Keep `SUPERVISED_SOURCE_IMPORTS_ENABLED` OFF.
   - Create one fictional canary business (synthetic Lumen) under an internal tenant.
   - Set `SUPERVISED_SOURCE_IMPORTS_BUSINESS_IDS=<that business UUID>` on the API.
   - Upload the synthetic Lumen export through the normal authenticated Studio/API routes, then build it.
   - Then confirm:
     - the job is claimed, built and accepted;
     - the import reaches `preview_ready`;
     - QA evidence is current and passed;
     - the preview serves the stored artifact.
   - Do not approve or publish. Remove the business from the allowlist when the canary is done.
6. **Verify artifact intake.** Check the job metrics line, the stored artifact hash, and the Contract/QA states in Studio.
7. **Enable** for the supervised pilot only: preferably by allowlisting the pilot business in `SUPERVISED_SOURCE_IMPORTS_BUSINESS_IDS`; turn on `SUPERVISED_SOURCE_IMPORTS_ENABLED=true` only when every business should have access.
8. **Supervised pilot:** one owner-reviewed export at a time, with operator review of every finding.

**Immediate disable.** Set `SUPERVISED_SOURCE_IMPORTS_ENABLED=false` on
the API, then redeploy or restart.

- Every source-import route except `capability` (which then reports `enabled: false`) answers 403 `feature_not_available`: no new import, review, reinspection or build.
- Published sites are untouched: they are stored artifacts served by Cloudflare, and nothing in the publish path reads the flag.
- Optionally scale the worker to 0. Queued jobs stay queued, and running ones finish or expire.

**Rollback of the worker.** Redeploy the previous worker deployment, or
remove the service. The API and published sites do not depend on it.

## 15. What still blocks creating the worker

- **Owner decisions.** Accept supervised-process mode (no sandbox) for owner-reviewed exports on Railway, and approve the service, its sizing and the new worker token and signing key.
- **Railway configuration.**
  - Confirm the service can be kept off the project's private network, or that the network reaches nothing sensitive.
  - Confirm the healthcheck works with `PORT` on a service without a public domain.
  - Confirm the 5-minute upload window for real operator uploads.
- **First real job.** Confirm peak memory and CPU against Railway's metrics.
- **Unchanged from R5:** first-pilot BusinessTruth and legal inputs, and no Higgsfield automation.

## 16. Scoped canary access (R5.1.1)

`SUPERVISED_SOURCE_IMPORTS_BUSINESS_IDS`: exact canonical business UUIDs,
separated by commas and/or whitespace. The default is empty, which means
no business has scoped access.

**When the capability is usable.** For a request about business X, the
supervised-import capability is usable when the global flag is on, OR X
is in the allowlist. Otherwise every lifecycle route answers 403
`feature_not_available`, as before.

**What the allowlist does not touch.** It never replaces any other check:

- the session and CSRF;
- `TenantAccess` for `X-Tenant-Id`;
- the business belonging to that tenant;
- rows filtered by tenant AND path business;
- review, blockers, plan and snapshot identity;
- the worker protocol;
- the artifact gate, approval and publish.

**One gate.** All seven lifecycle routes depend on
`require_supervised_import_access`; a test asserts this.

**Capability response.** `capability` returns `access`
(`global` | `scoped` | `disabled`) for the caller's own authorized
business. It never returns the allowlist.

**Fail closed.** Any malformed entry (`*`, `all`, a prefix, braces, a URN,
hex without hyphens, junk) disables scoped access for every business. The
failure is logged without the configured values.

**Removing an entry.** It closes all seven routes for that business
immediately. A job already queued still completes its build; publishing
always requires a human approval of the exact artifact.

**Disable.** Clear `SUPERVISED_SOURCE_IMPORTS_BUSINESS_IDS` (and keep the
global flag OFF).
