#!/bin/sh
set -e

# Migrations before the app ever accepts traffic — a half-migrated
# schema must never be served against, and alembic.ini's
# script_location ("migrations") and prepend_sys_path (".") are both
# relative, so this has to run with apps/api as the working directory
# (Dockerfile.prod's WORKDIR), same as the dev entrypoint.
uv run alembic upgrade head

# No --reload here (unlike docker-entrypoint.sh's dev image) — this is
# the production process, not a hot-reload dev server. Railway sets
# $PORT and expects the app to bind to it; 8000 is only a fallback for
# any other environment that runs this image without setting it.
exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
