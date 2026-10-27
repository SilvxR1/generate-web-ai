# Local development isolation (DEV-1 to DEV-3)

Local work must never touch production: not the Railway API or database,
not Cloudflare, R2, n8n or DNS, and not paid providers. This page covers
how the pieces are kept apart, how to check a machine before starting
anything, and the one safe startup order.

## Where configuration comes from

| Process | Reads | Production risk if misconfigured |
|---|---|---|
| API (`uvicorn`), `alembic`, `apps/api/scripts/*` | shell environment, then the dotenv file named by `GWA_ENV_FILE` (default `.env`, relative to the working directory, normally `apps/api`) | database, R2, n8n, email, paid providers |
| `docker compose up backend` | the same `apps/api/.env` (bind-mounted), with `DATABASE_URL`, `ENVIRONMENT`, `CORS_ORIGINS` and `CREDENTIAL_ENCRYPTION_KEY` overridden by the compose file. It also runs `alembic upgrade head` on start | every provider key in `.env`, and the database it migrates |
| API tests (`pytest`) | **nothing from disk.** See [Tests](#tests) | none (guarded) |
| Studio `vite` (`pnpm dev`) | shell, then `.env.development.local` > `.env.development` > `.env.local` > `.env` | calls the API it is pointed at |
| Studio `vite build` | shell, then `.env.production.local` > `.env.production` > `.env.local` > `.env` | — (this is the production build) |
| Studio `vite preview` | nothing: it serves an existing build, with the API URL baked in when it was built | `dist/` is a production build |
| Studio tests (`vitest`) | `VITE_API_URL` forced to `http://api.test.invalid`; unmocked requests are blocked (`src/test/networkGuard.ts`) | none (guarded) |

The real production values live in Railway's variables and in the operator's
own credential file outside the repository. A local checkout holds **local
values only**.

## First startup, in order

Every step is run by the operator, in their own terminal, from the repo root
unless it says otherwise. Do each checkpoint before its step; stop at the
first one that fails.

### a. Protect and relocate the production credentials

The existing `apps/api/.env` holds real production values. Move it out of
the repository. `mv` on the same filesystem is an atomic rename, so no copy
is left behind:

```sh
install -d -m 700 ~/.config/gwa
test ! -e ~/.config/gwa/.env.production && mv -n apps/api/.env ~/.config/gwa/.env.production
chmod 600 ~/.config/gwa/.env.production
test ! -e apps/api/.env && test -s ~/.config/gwa/.env.production && echo "moved"
```

- Keep the name `.env.production` in `~/.config/gwa/`. That directory is
  covered by the project's guards: `Read`/`Edit` deny rules in
  `.claude/settings.json`, the Read/Grep/Edit hook (`protect_files.py`), and
  the Bash guard (`prod_guard.py`), which only lets `ls`, `test`, `[` and
  `stat` name it.
- Do not rename it inside `apps/api`. `.dockerignore` excludes only
  `apps/api/.env`, and `railway up` uploads the directory.

### b. Create a fresh local `.env`

Checkpoint: `apps/api/.env` does not exist, and
`env | cut -d= -f1 | grep -xE 'DATABASE_URL|ENVIRONMENT|GWA_ENV_FILE'` prints
nothing.

```sh
cd apps/api && cp .env.example .env && chmod 600 .env
```

Leave every provider key empty. Without them, uploads go to local disk
(`var/uploads`), email delivery is off, and leads record n8n as not
configured. Do not set `N8N_BASE_URL`: local GWA is not connected to n8n. If
a local feature needs `CREDENTIAL_ENCRYPTION_KEY`, generate a fresh local
key. Never reuse production's.

### c. Run the local environment checker

```sh
cd apps/api && .venv/bin/python scripts/check_local_env.py
```

It loads the settings exactly as a local `uvicorn` or `alembic` run would,
and resolves Studio's development API the way `vite` does. It prints
classifications only (setting names, `loopback` or `remote`, `set`): never a
URL, host, token or password. Empty `KEY=` lines count as unset.

Required: exit status 0 and `Verdict: safe for local services.`, with
`DATABASE_URL: postgresql, loopback host`. Exit status 1 means at least one
`UNSAFE` finding, so **do not start anything**; 2 means the settings could
not be loaded.

### d. Start only the gwa-local PostgreSQL

Checkpoint: `ss -ltnp | grep -E ':(5432|8000|5173)\b'` prints nothing (no
other database or tunnel holds the port), and `docker ps` does not list
`generate-web-ai-postgres-1`.

```sh
docker compose -p gwa-local up -d postgres
```

- `-p gwa-local` is a separate Compose project with its own, empty volume
  (`gwa-local_postgres_data`). The older `generate-web-ai` project's
  container and `generate-web-ai_postgres_data` volume are left untouched.
- Always name the `postgres` service. A plain `docker compose up` also
  starts the backend container, which loads `apps/api/.env` and migrates
  whatever database it reaches.

### e. Verify the database target

```sh
docker compose -p gwa-local ps                      # postgres: running (healthy)
docker volume ls --format '{{.Name}}' | grep gwa-local_postgres_data
docker inspect generate-web-ai-postgres-1 --format '{{.State.Status}}'   # still: exited
ss -ltnp | grep ':5432\b'                           # owned by docker-proxy
cd apps/api && .venv/bin/python scripts/check_local_env.py               # still exit 0
```

A loopback `DATABASE_URL` is only safe if this container owns port 5432: a
tunnel on that port would also look like `localhost`.

### f. Apply migrations locally

```sh
cd apps/api && .venv/bin/alembic upgrade head
```

### g. Run the fictional seed

```sh
cd apps/api && .venv/bin/python scripts/seed_local_dev.py --confirm-local-seed
```

It creates one fictional tenant (`GWA Local Dev (ficticio)`), one fictional
business (`Panadería La Prueba (ficticia)`) and one owner,
`operator@gwa-local.example`, whose password it prompts for (hidden, never
printed). Before connecting, it refuses unless `ENVIRONMENT` is exactly
`development` and `DATABASE_URL` is PostgreSQL on a loopback host whose
host, database and user names don't look like production. After connecting,
it refuses if the database holds any other tenant, or if a row with one of
its fixed ids isn't its own. Re-running it creates nothing new and never
changes the operator's password.

### h. Start the local API and Studio

```sh
cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Checkpoint: `curl -s http://127.0.0.1:8000/health` reports
`"environment":"development"` and the database as `"ok"`.

Studio, from the repo root, one of the two (both use port 5173):

```sh
pnpm --filter @generate-web-ai/studio dev:local       # dev server, API forced to localhost
pnpm --filter @generate-web-ai/studio preview:local   # local build + preview on :5173
```

Log in as `operator@gwa-local.example`. In the browser's network tab, every
API request must go to `localhost:8000`.

- `dev:local` and `preview:local` set `VITE_API_URL` in the process
  environment, which takes priority over every `.env*` file.
- `preview:local` builds in development mode into
  `node_modules/.local-preview` (never `dist/`, which is what gets deployed)
  and serves it on 5173, the API's default CORS origin.
- **Do not use plain `pnpm preview`**: it serves `dist/`, a production build
  that calls the production API.

Local login works over plain http: in development the session cookie is
`SameSite=Lax` and not `Secure` (`app/auth/cookies.py`), and
`localhost:5173` and `localhost:8000` are the same site.

### Stopping

Stop `uvicorn` and Studio with Ctrl-C, then
`docker compose -p gwa-local stop postgres`. Use `stop`, never `down -v`,
which deletes the local volume.

## Still outside these guards

- The Railway CLI is linked to the repo root and `apps/api`.
  `railway run …` there injects production variables.
- The local `n8n` container runs on its own (`unless-stopped`) with
  workflows nobody has reviewed. Local GWA never calls it, but its own
  scheduled workflows could.
- Scripts in `apps/api/scripts/` other than the two above are for specific
  QA runs. Read one before running it.

## Tests

`apps/api/conftest.py` installs `tests/isolation.py` before any `app`
module is imported:

- `GWA_ENV_FILE=""` turns dotenv loading off, so `apps/api/.env` is never
  read. `DATABASE_URL` is forced to in-memory SQLite and `ENVIRONMENT` to
  development.
- The suite refuses to start (reporting names only) if dotenv loading is
  still on, the database is not SQLite, or any setting differs from its
  code default. That catches credentials exported in the shell.
- A Python audit hook blocks opening the repo's real `.env` files, and
  blocks connections and DNS lookups to anything but loopback (lookups of
  the never-resolvable `.invalid` TLD are allowed). A breach raises an
  `AssertionError` subclass, and a test whose code swallows it still fails
  at teardown. Python child processes given an explicit `env=` also get
  `GWA_ENV_FILE=""`.

The hook is defence in depth, not subprocess isolation. Non-Python children
(`astro build`, `pnpm`, `sh`) are limited only by the environment they
inherit, and that environment no longer carries any credentials.

```sh
cd apps/api && .venv/bin/python -m pytest -q
```

`GWA_ALLOW_REAL_PROVIDERS=1` is the only opt-in, for `pytest -m
real_provider` (paid calls, which need the operator's approval). It keeps
dotenv loading and lifts the hook and the credential check. The database
stays SQLite. With the credentials moved, it also needs `GWA_ENV_FILE`
pointing at them.
