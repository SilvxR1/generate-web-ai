#!/usr/bin/env bash
# v0.2 R4.1 — production execution-host acceptance.
#
# Run ON the candidate execution host, as the exact OS user and inside the
# exact runtime (image, kernel, cgroup setup) the worker will use in
# production. A local or CI result never substitutes for this run.
#
# Passes only if:
#   1. `python -m app.worker --selftest` reports ready (the sandbox can be
#      created AND every required limit — incl. cgroup memory and process
#      count — is enforced), and
#   2. both R4 malicious-fixture suites pass with ZERO skips.
#
# Prints a one-line verdict. It makes no call to the production API, the
# provider or any paid service.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== host"
uname -srm
id

echo "== selftest"
uv run python -m app.worker --selftest

echo "== malicious-fixture suites"
report="$(mktemp)"
trap 'rm -f "$report"' EXIT
uv run pytest -q -rs -p no:cacheprovider \
  tests/test_v0_2_r4_isolated_worker.py \
  tests/test_v0_2_r4_1_execution_host.py | tee "$report"

if grep -qE "[0-9]+ (skipped|xfailed|xpassed|deselected)" "$report"; then
  echo "R4_HOST_ACCEPTANCE=FAIL (a test was skipped or deselected — acceptance requires every test to run)"
  exit 1
fi
echo "R4_HOST_ACCEPTANCE=PASS"
