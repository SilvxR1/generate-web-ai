"""R5.1 — what the build worker verifies BEFORE it claims any job.

The worker holds exactly two pieces of configuration that matter: the
control plane's URL and its own claim-only token. Everything else a
production service might carry (database, storage, Cloudflare, email,
n8n, provider keys, the API's own signing secrets) must be ABSENT. The
denylist below is derived from the API's real settings (app.config) plus
the platform-level names a shared Railway environment could inject, so
an accidentally inherited credential stops the worker instead of sitting
next to customer-supplied code. Only variable NAMES are ever reported,
never values.

    python -m app.worker --preflight     # JSON report; exit 0 = ready

This is defense in depth, not isolation: in supervised-process mode the
worker is NOT a sandbox (see SupervisedProcessRunner). It is what makes
"the worker has no platform credential" checkable on every start.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app.config import Settings

# Settings families that belong to the API process only. Any environment
# variable named after one of these fields is forbidden on the worker.
_API_ONLY_SETTING_PREFIXES = (
    "database_",
    "credential_",
    "n8n_",
    "anthropic_",
    "generation_worker_",
    "internal_automation_",
    "cloudflare_",
    "smtp_",
    "resend_",
    "higgsfield_",
    "google_reviews_",
    "r2_",
    "alert_webhook_",
)
# Names a platform (Railway shared variables, a Postgres plugin, CI) or a
# developer could inject that the API settings do not name directly.
_PLATFORM_SECRETS = frozenset(
    {
        "DATABASE_PUBLIC_URL",
        "DATABASE_PRIVATE_URL",
        "POSTGRES_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "REDIS_URL",
        "OPENAI_API_KEY",
        "CF_API_TOKEN",
        "CF_ACCOUNT_ID",
        "CLOUDFLARE_API_KEY",
        "CLOUDFLARE_EMAIL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "RAILWAY_TOKEN",
        "RAILWAY_API_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "NPM_TOKEN",
        "NODE_AUTH_TOKEN",
        "PUBLIC_API_BASE_URL",
    }
)
# Generic credential-shaped names (any service). The worker's own token is
# the single allowed exception.
_CREDENTIAL_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|SECRET_KEY|PASSWORD|PASSWD|API_KEY|KEY|PRIVATE_KEY|ACCESS_KEY|CREDENTIALS?)$"
)
_URL_WITH_PASSWORD = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
WORKER_TOKEN_ENV = "GWA_WORKER_TOKEN"
API_URL_ENV = "GWA_API_BASE_URL"
ALLOWED_CREDENTIAL_NAMES = frozenset({WORKER_TOKEN_ENV})
MIN_TOKEN_CHARS = 32
NODE_MAJOR = 24
BUN_MIN = (1, 4)
MIN_FREE_BYTES = 2 * 1024**3
MIN_MEMORY_BYTES = 2 * 1024**3
SUPPORTED_CONCURRENCY = 1


def api_only_setting_names() -> frozenset[str]:
    return frozenset(name.upper() for name in Settings.model_fields if name.startswith(_API_ONLY_SETTING_PREFIXES))


def forbidden_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """NAMES of variables the worker must never hold (values are only
    inspected for an embedded-password URL shape and never returned)."""
    environ = os.environ if environ is None else environ
    denied = api_only_setting_names() | _PLATFORM_SECRETS
    found = []
    for name, value in environ.items():
        upper = name.upper()
        if upper in ALLOWED_CREDENTIAL_NAMES or not value:
            continue
        if upper in denied or _CREDENTIAL_NAME.search(upper) or _URL_WITH_PASSWORD.match(value):
            found.append(name)
    return sorted(found)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)
    facts: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]

    def to_json(self) -> str:
        return json.dumps(
            {
                "ready": self.ok,
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
                "facts": self.facts,
            },
            sort_keys=True,
        )


def validate_api_url(raw: str | None) -> str:
    """https:// with a host and nothing else; plain http only to loopback
    (local tests). Raises ValueError with a safe message."""
    value = (raw or "").strip()
    if not value:
        raise ValueError(f"{API_URL_ENV} is not set")
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise ValueError(f"{API_URL_ENV} must not embed credentials")
    if parts.query or parts.fragment:
        raise ValueError(f"{API_URL_ENV} must not carry a query or fragment")
    if not parts.hostname:
        raise ValueError(f"{API_URL_ENV} has no host")
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError(f"{API_URL_ENV} must be an https:// URL")
    return value.rstrip("/")


def read_worker_token(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    credentials = environ.get("CREDENTIALS_DIRECTORY")
    if credentials:
        path = Path(credentials) / "worker-token"
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    return environ.get(WORKER_TOKEN_ENV, "").strip()


def _version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv, capture_output=True, text=True, timeout=30, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _numbers(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def container_memory_limit() -> int | None:
    """cgroup v2/v1 memory limit of this container, when one is visible."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 60:
            return int(raw)
    return None


def browser_env(home: Path) -> dict[str, str]:
    """Chromium's whole environment: no worker credential, no platform
    variable — a private HOME/TMPDIR inside the job workspace."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
    }


def _chromium_launches() -> str:
    """Actually launches headless Chromium (with no inherited environment)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright is not installed"
    try:
        with tempfile.TemporaryDirectory(prefix="gwa-preflight-chromium-") as home, sync_playwright() as pw:
            env: dict[str, str | float | bool] = dict(browser_env(Path(home)))
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"], env=env)
            version = browser.version
            browser.close()
            return f"ok {version}"
    except Exception as exc:  # noqa: BLE001 — any launch failure means not ready
        first = (str(exc).splitlines() or [""])[0]
        return f"cannot launch: {type(exc).__name__}: {first[:200]}"


def init_protection(proc_root: str = "/proc") -> tuple[bool, str]:
    """R5.2: when the worker is NOT PID 1 (it runs under app.worker.init),
    PID 1 holds the same startup environment, so it must be unreadable to
    this UID too. A dumpable init (e.g. stock tini) fails closed here."""
    if os.getpid() == 1:
        return True, "the worker is PID 1 (its own protection applies)"
    try:
        with open(f"{proc_root}/1/environ", "rb") as handle:
            handle.read(1)
    except PermissionError:
        return True, "PID 1's environment is unreadable to this user"
    except OSError as exc:
        return True, f"PID 1's environment is not accessible ({type(exc).__name__})"
    return False, "PID 1's environment is readable by this user (a dumpable init would expose the token)"


def run_preflight(
    *,
    environ: Mapping[str, str] | None = None,
    isolation: str,
    work_root: Path,
    launch_chromium: bool = True,
    which: Callable[[str], str | None] = shutil.which,
) -> PreflightReport:
    environ = os.environ if environ is None else environ
    report = PreflightReport()
    add = report.checks.append

    from app.worker.process_protection import is_non_dumpable  # noqa: PLC0415

    protected = is_non_dumpable()
    add(
        Check(
            "process_protection",
            protected,
            "non-dumpable: same-UID processes cannot read this process via procfs"
            if protected
            else "the process is dumpable (PR_SET_DUMPABLE not applied)",
        )
    )
    init_ok, init_detail = init_protection()
    add(Check("init_protection", init_ok, init_detail))
    forbidden = forbidden_environment(environ)
    detail = f"forbidden variables present: {', '.join(forbidden)}" if forbidden else "none present"
    add(Check("no_platform_credentials", not forbidden, detail))
    try:
        url = urlsplit(validate_api_url(environ.get(API_URL_ENV)))
        add(Check("api_url", True, f"{url.scheme}://{url.hostname}"))
    except ValueError as exc:
        add(Check("api_url", False, str(exc)))
    token = read_worker_token(environ)
    token_ok = len(token) >= MIN_TOKEN_CHARS and not re.search(r"\s", token)
    add(Check("worker_token", token_ok, "present" if token_ok else f"missing or shorter than {MIN_TOKEN_CHARS} chars"))
    add(Check("isolation_mode", isolation in ("bubblewrap", "supervised-process"), isolation))
    concurrency = environ.get("GWA_WORKER_CONCURRENCY", str(SUPPORTED_CONCURRENCY)).strip()
    add(
        Check(
            "concurrency",
            concurrency == str(SUPPORTED_CONCURRENCY),
            f"{concurrency} (one build per worker process; scale with replicas)",
        )
    )
    add(Check("python", sys.version_info >= (3, 12), sys.version.split()[0]))
    report.facts["app_version"] = Settings.model_fields["version"].default
    report.facts["build_commit"] = environ.get("RAILWAY_GIT_COMMIT_SHA") or environ.get("GWA_BUILD_COMMIT") or None

    node = which("node")
    node_version = _version([node, "--version"]) if node else None
    node_ok = bool(node_version) and _numbers(node_version or "")[:1] == (NODE_MAJOR,)
    add(Check("node", node_ok, node_version or "node not found"))
    bun = which("bun")
    bun_version = _version([bun, "--version"]) if bun else None
    add(Check("bun", bool(bun_version) and _numbers(bun_version or "")[:2] >= BUN_MIN, bun_version or "bun not found"))
    if launch_chromium:
        chromium = _chromium_launches()
        add(Check("chromium", chromium.startswith("ok"), chromium))

    try:
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work_root, prefix="preflight-") as probe:
            (Path(probe) / "write-test").write_bytes(b"x" * 4096)
        free = shutil.disk_usage(work_root).free
        add(Check("workspace", free >= MIN_FREE_BYTES, f"writable, {free // 1024**2} MiB free"))
    except OSError as exc:
        add(Check("workspace", False, f"not writable: {type(exc).__name__}"))
    add(Check("no_dotenv", not Path(".env").exists(), "no .env in the working directory"))
    memory = container_memory_limit()
    report.facts["memory_limit_bytes"] = memory
    report.facts["cpu_count"] = os.cpu_count()
    memory_detail = "no container limit visible" if memory is None else f"{memory // 1024**2} MiB limit"
    add(Check("memory", memory is None or memory >= MIN_MEMORY_BYTES, memory_detail))
    return report
