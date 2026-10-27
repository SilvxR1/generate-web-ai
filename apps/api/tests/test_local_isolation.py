"""DEV-1: the API suite never reads real configuration, never uses a real
database and never reaches a non-loopback host (tests/isolation.py).

The negative tests point the guard at names that do not exist or at
reserved, never-routed addresses (192.0.2.0/24 is TEST-NET-1; the `.example`
and `.invalid` TLDs are reserved by RFC 2606), so even a broken guard could
not touch a real file or host.
"""

import os
import socket
import subprocess
import sys

import httpx
import pytest

from app.config import Settings, settings
from tests import isolation
from tests.isolation import API_ROOT, expected_breach

pytestmark = pytest.mark.skipif(isolation.REAL_PROVIDERS_OPT_IN, reason="isolation is lifted by the opt-in")

FAKE_SECRET = "dev1-fake-secret-value-never-printed"
CREDENTIAL_SETTINGS = (
    "anthropic_api_key",
    "credential_encryption_key",
    "n8n_base_url",
    "n8n_api_key",
    "internal_automation_token",
    "cloudflare_account_id",
    "cloudflare_api_token",
    "smtp_host",
    "smtp_password",
    "resend_api_key",
    "higgsfield_api_key",
    "higgsfield_api_key_id",
    "higgsfield_api_key_secret",
    "r2_account_id",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket_name",
    "r2_private_bucket_name",
    "google_reviews_api_key",
    "generation_worker_token_sha256",
    "generation_worker_signing_key",
    "alert_webhook_url",
)


def _isolated_child_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "GWA_ALLOW_REAL_PROVIDERS"}
    return {**env, **extra}


# --- Settings ---------------------------------------------------------------------------------------


def test_dotenv_loading_is_disabled():
    assert os.environ["GWA_ENV_FILE"] == ""
    assert Settings.model_config.get("env_file") is None


def test_no_credential_or_provider_setting_is_configured():
    assert [name for name in CREDENTIAL_SETTINGS if getattr(settings, name) is not None] == []
    assert settings.higgsfield_cli_enabled is False
    assert settings.environment == "development"
    assert isolation.settings_problems(Settings, settings) == []


def test_the_database_is_in_memory_sqlite_including_the_module_engine():
    from app.dependencies import engine

    assert settings.database_url == "sqlite://"
    assert engine.url.get_backend_name() == "sqlite"
    assert engine.url.database in (None, "")


def test_a_remote_database_is_rejected():
    remote = Settings(database_url="postgresql+psycopg://user:pass@db.example.invalid:5432/app")

    problems = isolation.settings_problems(Settings, remote)

    assert "DATABASE_URL is not SQLite" in problems
    assert all("pass@" not in p and "example.invalid" not in p for p in problems)


def test_a_credential_is_rejected_by_name_never_by_value():
    leaked = Settings(r2_secret_access_key=FAKE_SECRET, environment="production")

    problems = isolation.settings_problems(Settings, leaked)

    assert "ENVIRONMENT is production" in problems
    assert any("R2_SECRET_ACCESS_KEY" in p for p in problems)
    assert all(FAKE_SECRET not in p for p in problems)


def test_the_suite_refuses_to_start_with_a_credential_in_the_shell():
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_health.py"],
        cwd=API_ROOT,
        env=_isolated_child_env(ANTHROPIC_API_KEY=FAKE_SECRET),
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "refuse to start outside isolation" in output and "ANTHROPIC_API_KEY" in output
    assert FAKE_SECRET not in output


def test_a_shell_database_url_is_overridden_not_used():
    code = "from app.config import settings; print(settings.database_url)"
    completed = subprocess.run(
        [sys.executable, "-c", f"from tests import isolation; isolation.install(); {code}"],
        cwd=API_ROOT,
        env=_isolated_child_env(DATABASE_URL="postgresql+psycopg://user:pass@db.example.invalid/app"),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.stdout.strip() == "sqlite://", completed.stderr


# --- dotenv files -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        os.path.join(API_ROOT, ".env.dev1-guard-probe"),
        os.path.join(isolation.REPO_ROOT, "apps", "studio", ".env.dev1-guard-probe"),
        ".env.dev1-guard-probe",  # relative to the working directory (apps/api)
    ],
)
def test_opening_a_real_env_file_is_blocked(path):
    with expected_breach():
        open(path)  # never reached: the guard raises before the open
    assert not os.path.exists(path)


def test_the_real_env_file_names_are_recognised_without_opening_them():
    assert isolation.is_real_env_file(os.path.join(API_ROOT, ".env"))
    assert isolation.is_real_env_file(os.path.join(isolation.REPO_ROOT, "apps", "studio", ".env.local"))
    assert not isolation.is_real_env_file(os.path.join(API_ROOT, ".env.example"))


def test_an_env_file_in_a_tmp_workspace_is_allowed(tmp_path):
    fixture = tmp_path / ".env"
    fixture.write_text("TOKEN=x\n")
    assert fixture.read_text() == "TOKEN=x\n"


def test_a_python_child_with_an_explicit_env_never_loads_dotenv():
    # The shape of test_r5_1_worker_readiness's import probe: cwd=apps/api and a
    # minimal env without GWA_ENV_FILE, which would otherwise read apps/api/.env.
    # The child's own hook aborts before any .env open, so even a failure here
    # never reads the real file.
    code = (
        "import os, sys\n"
        "def hook(event, args):\n"
        "    if event == 'open' and isinstance(args[0], (str, bytes))"
        " and os.path.basename(os.fsdecode(args[0])).startswith('.env'):\n"
        "        os._exit(3)\n"
        "sys.addaudithook(hook)\n"
        "from app.config import Settings\n"
        "print(repr(Settings.model_config['env_file']))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.stdout.strip() == "None", completed.stderr


# --- Network ----------------------------------------------------------------------------------------


def test_connecting_to_a_non_loopback_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, expected_breach():
        sock.connect(("192.0.2.1", 9))


def test_udp_to_a_non_loopback_address_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, expected_breach():
        sock.sendto(b"x", ("192.0.2.1", 9))


def test_dns_lookups_of_external_names_are_blocked():
    with expected_breach():
        socket.getaddrinfo("dev1-guard-probe.example", 443)


def test_only_the_never_resolvable_invalid_tld_is_exempt_from_the_dns_guard():
    assert isolation.is_never_resolvable("hooks.example.invalid")
    assert isolation.is_never_resolvable("hooks.example.invalid.")
    assert not isolation.is_never_resolvable("invalid.example")
    assert not isolation.is_never_resolvable("generate-web-ai-repo-production.up.railway.app")


def test_an_http_client_call_is_blocked_not_mapped_to_a_connect_error():
    with expected_breach():
        httpx.get("http://192.0.2.1:9/", timeout=1)


def test_a_swallowed_breach_is_still_recorded():
    with expected_breach(swallowed=True):
        try:
            socket.getaddrinfo("dev1-guard-probe.example", 443)
        except Exception:  # the code under test hides every error
            pass


def test_loopback_connections_are_allowed():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5):
            pass


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("::ffff:127.0.0.1", True),
        ("localhost", True),
        (None, True),
        ("0.0.0.0", False),
        ("192.0.2.1", False),
        ("::ffff:192.0.2.1", False),
        ("generate-web-ai-repo-production.up.railway.app", False),
        ("api.anthropic.com", False),
        ("localhost.example", False),
    ],
)
def test_loopback_classification(host, loopback):
    assert isolation.is_loopback_host(host) is loopback
