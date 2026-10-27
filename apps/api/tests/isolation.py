"""Test-process isolation for the API suite (DEV-1), installed by the rootdir
conftest.py before tests/conftest.py and before any `app` module is imported.
That is the only point where it can still decide what app.config's
module-level `settings = Settings()` reads.

1. Safe environment (install). GWA_ENV_FILE="" turns dotenv loading off (see
   app.config), so a developer's apps/api/.env and its real credentials are
   never read. DATABASE_URL is forced to in-memory SQLite and ENVIRONMENT to
   development, whatever the shell exports.
2. Settings check (settings_problems). The suite refuses to start if the
   settings still enable dotenv, name a non-SQLite database, or carry any
   value other than its code default, which would mean credentials exported
   in the shell. Only setting NAMES are reported, never values.
3. Audit hook (defence in depth). It blocks opening the repo's real .env
   files, connecting anywhere but loopback, and resolving any name but
   loopback ones and the never-resolvable `.invalid` TLD. Python children
   given an explicit `env=` mapping get GWA_ENV_FILE="" added; children that
   inherit the environment already have it. The hook only sees this process,
   so it is not subprocess isolation: a non-Python child (astro, pnpm, sh) is
   limited only by the environment it inherits.

GWA_ALLOW_REAL_PROVIDERS=1 is the one explicit opt-in, for `pytest -m
real_provider` (paid calls, which need the operator's approval). It keeps
dotenv loading and lifts the audit hook and the credential check, but the
database stays SQLite.
"""

import contextlib
import ipaddress
import os
import socket
import sys
import threading
from collections.abc import Iterator

API_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(API_ROOT))
REAL_PROVIDERS_OPT_IN = os.environ.get("GWA_ALLOW_REAL_PROVIDERS") == "1"

# Directories whose .env files hold real configuration. Fixtures that write a
# `.env` into a tmp workspace (source-adapter tests) are unaffected.
REAL_ENV_DIRS = frozenset({API_ROOT, REPO_ROOT, os.path.join(REPO_ROOT, "apps", "studio")})
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "ip6-localhost"})
# Settings the bootstrap itself forces; every other one must keep its default.
_FORCED_SETTINGS = frozenset({"database_url", "environment"})


class IsolationBreach(AssertionError):
    """A test tried to read a real .env file or reach a non-loopback host.

    An AssertionError, like conftest's RealSmtpConnectionBlocked, so code
    catching OSError or httpx errors cannot turn it into a normal failure.
    Breaches are also recorded, so a test whose code swallows the exception
    still fails at teardown (conftest's _fail_on_swallowed_isolation_breach)."""


breaches: list[str] = []
_in_hook = threading.local()


def is_real_env_file(path: object) -> bool:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False  # an fd
    path = os.fsdecode(path)
    name = os.path.basename(path)
    if name != ".env" and not (name.startswith(".env.") and name != ".env.example"):
        return False
    return os.path.dirname(os.path.realpath(path)) in REAL_ENV_DIRS


def is_loopback_host(host: object) -> bool:
    if host is None:
        return True  # getaddrinfo(None, ...) means the local host
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    host = host.strip("[]").split("%", 1)[0].lower()
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # any other name would be resolved through DNS
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback


def is_never_resolvable(host: object) -> bool:
    """`.invalid` (RFC 6761) never resolves to a real host. Existing tests use
    it as their "unreachable webhook", so looking it up stays allowed; any
    connection would still need a loopback address."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return isinstance(host, str) and host.lower().rstrip(".").endswith(".invalid")


def _is_python(executable: object, args: object) -> bool:
    program = executable
    if program is None and isinstance(args, (list, tuple)) and args:
        program = args[0]
    if not isinstance(program, (str, bytes, os.PathLike)):
        return False
    program = os.fsdecode(program)
    return program == sys.executable or os.path.basename(program).startswith("python")


def _breach(message: str) -> None:
    breaches.append(message)
    raise IsolationBreach(f"{message}: the API test suite runs isolated from real configuration (tests/isolation.py)")


def _audit(event: str, args: tuple) -> None:
    if getattr(_in_hook, "active", False):
        return
    _in_hook.active = True
    try:
        if event == "open":
            if is_real_env_file(args[0]):
                _breach(f"opened a real env file ({os.path.basename(os.fsdecode(args[0]))})")
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            sock, address = args[0], args[1]
            if (
                getattr(sock, "family", None) in (socket.AF_INET, socket.AF_INET6)
                and isinstance(address, tuple)
                and not is_loopback_host(address[0])
            ):
                _breach(f"{event} to non-loopback host {address[0]!r}")
        elif event == "socket.getaddrinfo":
            if not is_loopback_host(args[0]) and not is_never_resolvable(args[0]):
                _breach(f"DNS lookup of non-loopback host {args[0]!r}")
        elif event == "subprocess.Popen":
            executable, popen_args, _cwd, env = args
            if isinstance(env, dict) and _is_python(executable, popen_args):
                env.setdefault("GWA_ENV_FILE", "")
    finally:
        _in_hook.active = False


def install() -> None:
    """Runs once, from the rootdir conftest, before any `app` import."""
    if not REAL_PROVIDERS_OPT_IN:
        os.environ["GWA_ENV_FILE"] = ""
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["ENVIRONMENT"] = "development"
    if not REAL_PROVIDERS_OPT_IN:
        sys.addaudithook(_audit)  # audit hooks cannot be removed; it stays for the whole session


def settings_problems(
    settings_cls: type, settings: object, *, real_providers: bool = REAL_PROVIDERS_OPT_IN
) -> list[str]:
    """Why these settings are unsafe for the test suite, by setting NAME only."""
    problems = []
    if not real_providers and settings_cls.model_config.get("env_file") is not None:
        problems.append("dotenv loading is enabled (GWA_ENV_FILE is not empty)")
    if not settings.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL is not SQLite")
    if settings.environment == "production":
        problems.append("ENVIRONMENT is production")
    if not real_providers:
        overridden = sorted(
            name.upper()
            for name, field in settings_cls.model_fields.items()
            if name not in _FORCED_SETTINGS and getattr(settings, name) != field.get_default(call_default_factory=True)
        )
        if overridden:
            problems.append("set from the environment: " + ", ".join(overridden))
    return problems


@contextlib.contextmanager
def expected_breach(*, swallowed: bool = False) -> Iterator[None]:
    """For the isolation tests only: the block must breach exactly once, and
    that breach is then forgotten so the teardown check stays quiet."""
    start = len(breaches)
    if swallowed:
        yield
    else:
        try:
            yield
        except IsolationBreach:
            pass
        else:
            raise AssertionError("expected the isolation guard to block this")
    assert len(breaches) == start + 1, breaches[start:]
    del breaches[start:]
