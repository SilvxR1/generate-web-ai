# H1 — GWA Platform Adapter proof of concept (Higgsfield export → WebsiteArtifact)

Status: **proof of concept, local only.** Nothing is published, uploaded or
enabled; the generative feature gate is unchanged.

## Principle

Higgsfield is the **creative** authority; GWA is the **platform** authority.
The adapter never re-expresses an exported site as SiteConfig/blocks/Astro.
It keeps the exported source and changes only platform behavior and
business facts, through fixed, traceable edits.

## Pipeline (`app/creative/source_adapter`)

| Step | Module | Reusable? |
|---|---|---|
| Immutable, hash-identified snapshot of the export ZIP (safe extraction, per-file SHA-256, read-only) | `snapshot.py` | yes |
| Remove code that needs unavailable private workspace packages — only if unreachable from the public site; stop if the site needs them | `cleanup.py` | yes (TS/React exports) |
| Traceable primitives: exact-once patches, typed content bindings, new platform files | `records.py`, `mapping.py` | yes |
| Source-specific mapping (lead transport, legal routes, fonts, prerender, bindings) | `mappings/nexo_reformas.py` | **no** — one per export |
| Trusted `bun install --ignore-scripts` (validated inputs, scrubbed env) + the export's own build in the **R4 BubblewrapRunner** (no network) | `static_build.py` | yes (Bun/Vite family) |
| Static artifact: platform runtime + consent injected, platform-owned `robots.txt`/`sitemap.xml`/`_headers` | `static_artifact.py` | yes |
| Contracts, `artifact_sha256`, `pack_artifact` | `pipeline.py` | yes |
| Local preview that applies the artifact's own `_headers` (real CSP) | `preview.py` | yes |

Shared-code changes (each default-neutral, tested in `tests/test_h1_platform_extensions.py`):

- `security_headers.CspExtensions` — trusted per-source-family CSP additions
  (`media-src 'self' blob:`, exact https style/font origins). Default output
  byte-identical. `drafts.judge_generative_candidate(csp_extensions=…)` passes
  it through (default `None` = unchanged).
- `frontend_engine.build.inline_script_hashes` — hashes what the browser
  hashes (U+0000 → U+FFFD, CRLF → LF). TanStack's dehydrated state contains
  U+0000; the raw-byte hash made the real CSP block hydration. Unchanged for
  every Astro build.
- `frontend_engine.build.inject_platform_runtime` — the existing config +
  consent injection, exposed for reuse (same bytes).
- `frontend_engine.browser_qa` navigates to `/` (what hosts serve) instead of
  `/index.html`, which a client router treats as a different route.
- `legal_pages.legal_page_content` — the legal wording, rendered by both the
  Astro pages (unchanged) and exported sources.
- `truth_contract`: an email that appears in shipped JS **only** as a form
  `placeholder` value is not a published contact (mirrors the HTML rule).
  Any other occurrence still blocks.

## Result on the real export (nexo-reformas-web.zip)

- ZIP SHA-256 `f3fbc3e76caf53f8df4ae6d6819be7afcd24190af396172cd0ca68de31e0ea8f`
  (225 files, 31.1 MB, React 19 + TanStack Start 1.168 + Vite 8 + Tailwind 4, bun).
- Cleanup: 4 unavailable `@higgsfield/*` workspace packages, 1 unused route
  (`/app`), 42 unreachable scaffold modules, 9 CSS lines — identical to the
  portability spike's manual cleanup. No Nexo design file removed.
- Mapping: 15 patches, 14 BusinessTruth bindings, 8 new platform files,
  3 backend files removed, 2 OFL font packages added (72 recorded changes
  in total, including the cleanup).
- Build: TanStack Start's documented `prerender` → static `index.html`,
  `privacy/`, `terms/`, `cookies/`. Install ~2 s (trusted), build ~5 s in the
  R4 sandbox (bubblewrap + cgroup scope, all limits enforced, no network).
- Artifact: 124 files, 31.7 MB. PlatformContract 1.1.0 and TruthContract
  1.0.0: **0 findings**. Accepted READY by the real
  `judge_generative_candidate`, with the stored identity equal to the built one.
- Local preview QA (`scripts/h1_preview_qa.py`, real CSP, local GWA-compatible
  API from the real schemas/CORS/spam check): 41/42 checks pass; the one
  failure is a pre-existing Higgsfield 12 px mobile overflow (identical on the
  original). Screenshots at the spike's exact offsets: 0.00% pixels changed at
  19/20 positions, 0.63% at one (sub-pixel glyph rendering).

## Visible additions

1. Footer bottom bar: legal links + "Preferencias de cookies" (site's mono style).
2. `/privacy`, `/terms`, `/cookies` pages built from the site's own classes.
3. Platform consent banner, themed via `--gwa-consent-*` with the site's tokens.
4. Success state reads "Solicitud recibida" (the Lead API never returns an id; none is invented).
5. No `og:image` (the Higgsfield-CDN image was removed; GWA must set an owned one).

## Known limitations / required before a real customer

- **Intake must pass the source-family CSP.** `worker/intake.py` does not yet
  pass `csp_extensions`; without it the stored artifact loses
  `media-src blob:` + Fontshare and silently degrades (contracts cannot see CSP).
- **Visual QA must apply `_headers`.** `browser_qa` drops them, so a CSP that
  breaks the site passes QA. `preview.serve_artifact` shows the approach.
- **Build is not bit-reproducible**: TanStack writes `updatedAt` timestamps
  into the dehydrated state (5 files differ between builds). Packaging is
  deterministic and Build Once stores the built bytes, so identity holds.
- **Lead schema gaps**: no structured fields for surface area / service; they
  travel as `subject` + a labelled line in `message`.
- **Legal and consent copy are English** (platform text) on a Spanish site.
- **Cabinet Grotesk** stays on Fontshare's CSS API: its licence text for
  self-hosting could not be read; Inter Tight / IBM Plex Mono are self-hosted
  (OFL-1.1). Remote fonts expose visitor IPs to the font CDN (privacy review).
- **TruthContract logo detection gap**: images are treated as logos only if
  `alt`/`class`/`id` contain "logo". Nexo's generated brand mark
  (`.nx-nav__mark`) is not detected; no exemption was added.
- **Only name, city and country are bound.** Services, process and chapter
  copy are Higgsfield literals; Studio edits to them need a source change.
- **R4 for this family** needs bun (bound read-only), ~1–1.5 GB RAM for `tsc`,
  and a per-family prepared-dependency set (455 MB `node_modules`).
- Supercomputer generation is still manual (separate automation gap).

## Reproduce

```bash
cd apps/api
uv run python scripts/h1_higgsfield_adapter.py --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-h1/run
uv run python scripts/h1_preview_qa.py --work-root /tmp/gwa-h1/run --spike-visual /path/to/spike/visual
```
