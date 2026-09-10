# Higgsfield integration — configuration

This file documents the environment variables the Higgsfield creative
provider (`apps/api/app/creative/higgsfield/`) reads, kept separate from
`docs/architecture.md` per that document's own instruction. **No
credentials are committed here or anywhere else in this repository.**

## Status

No real Higgsfield API call is implemented yet — see
`docs/architecture.md`'s "Higgsfield integration status" section for why,
and what's needed to complete it. The variables below are already wired
into `app.config.Settings` and `app.dependencies.get_higgsfield_provider`
(a server without them still starts up fine; premium creative generation
fails loudly with a `503` the first time it's actually attempted), but
setting them does not yet make generation succeed — every provider method
currently raises `HiggsfieldNotIntegratedError` regardless.

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
