# Higgsfield integration — configuration

This file documents the environment variables/settings the two
Higgsfield integration paths in `apps/api/app/creative/higgsfield/` use,
kept separate from `docs/architecture.md` per that document's own
instruction. **No credentials are committed here or anywhere else in
this repository.**

## Status (updated in P2)

There are now **two distinct, independent Higgsfield integration
paths** in this codebase — do not conflate them:

1. **`HiggsfieldCreativeProvider`** (`app.creative.higgsfield.provider`)
   — the original P0-era HTTP/API-key-based boundary. Still exactly as
   documented below: every method raises `HiggsfieldNotIntegratedError`,
   `HIGGSFIELD_API_KEY`/`HIGGSFIELD_BASE_URL` are wired but inert. Left
   untouched in P2 — treat it as legacy/unintegrated scaffolding, not a
   contradiction of point 2 below.
2. **`HiggsfieldCreativeDirector`** (`app.creative.higgsfield.director`,
   P2) — the real, working integration, built on the `higgsfield` CLI's
   own already-authenticated local OAuth session instead of a server-held
   API key (see `docs/security.md`'s P2 section for why this is a
   documented limitation, not a design preference). Controlled by
   `higgsfield_cli_enabled`/`higgsfield_cli_binary`/
   `higgsfield_cli_timeout_seconds` in `app.config.Settings` — all
   default to disabled/sane defaults, so a server without the CLI
   installed and authenticated still starts up fine.
   `app.dependencies.get_optional_higgsfield_director` returns `None`
   (never raises) when `higgsfield_cli_enabled` is `False`, mirroring
   `get_optional_higgsfield_provider`'s shape. Verified end-to-end
   against the real, authenticated CLI during this P2 pass: 3
   `create_directions` + 3 `develop_direction` calls, 12 real Higgsfield
   credits spent (account balance 1108 → 1096), all mocked-subprocess
   unit tests in `tests/test_higgsfield_cli_director.py` passing
   alongside.

The rest of this document (environment variables below) describes path 1
only, unchanged from before P2.

## Required environment variables

Set these in `apps/api/.env` (never commit this file — it's already
git-ignored, same as every other credential in this project):

| Variable | Required for | Notes |
| --- | --- | --- |
| `HIGGSFIELD_API_KEY` | Any Higgsfield call | No default. Never logged (see `app.creative.higgsfield.client.HiggsfieldClient`). |
| `HIGGSFIELD_BASE_URL` | Any Higgsfield call | No default — this codebase does not assume any particular Higgsfield API host. |

Both must be set for `get_higgsfield_provider`/`get_optional_higgsfield_provider`
(`apps/api/app/dependencies.py`) to construct a `HiggsfieldCreativeProvider`
at all; either missing means Higgsfield is treated as "not configured" —
the same as never having set them.

## Adding these to `.env.example`

`apps/api/.env.example` should list the variable *names* only (as every
other provider credential in that file already does), never real values:

```
HIGGSFIELD_API_KEY=
HIGGSFIELD_BASE_URL=
```

## Completing the integration

Once Higgsfield's real API documentation is available, see
`docs/architecture.md`'s "Higgsfield integration status" section for the
exact steps (implementing the HTTP calls, mapping cost/credit fields,
adding contract tests). No additional environment variables should be
needed beyond the two above unless Higgsfield's real API requires more
(e.g. a separate webhook secret for async job completion) — add any such
variable to this table, `app.config.Settings`, and `.env.example` together,
following the same "no default, fail loud only when used" pattern already
used for every other optional provider in this codebase.
