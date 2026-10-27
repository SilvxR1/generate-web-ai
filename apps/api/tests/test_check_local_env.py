"""DEV-1: scripts/check_local_env.py classifies configuration and never prints
a value. Every input here is a fake in tmp_path; the real apps/api/.env and
apps/studio/.env.local are never read (tests/isolation.py would block them).
"""

import importlib.util
import os
import subprocess
import sys

import pytest

from app.config import Settings
from tests.isolation import API_ROOT

SCRIPT = os.path.join(API_ROOT, "scripts", "check_local_env.py")
FAKE_SECRET = "dev1-fake-secret-value-never-printed"
REMOTE_HOST = "db.example.invalid"

_spec = importlib.util.spec_from_file_location("check_local_env", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _levels(findings) -> dict[str, str]:
    return {f.subject: f.level for f in findings}


def test_a_local_configuration_has_no_unsafe_finding():
    local = Settings(
        database_url="postgresql+psycopg://generate_web_ai:generate_web_ai@localhost:5432/generate_web_ai",
        n8n_base_url="http://localhost:5678",
        n8n_api_key=FAKE_SECRET,
    )

    findings = check.classify_api(Settings, local)

    assert [f for f in findings if f.level == "UNSAFE"] == []
    assert _levels(findings)["DATABASE_URL"] == "OK"
    assert _levels(findings)["N8N_API_KEY"] == "OK"


def test_empty_optional_settings_count_as_unset():
    # What an `.env` copied from `.env.example` produces: `KEY=` lines load as "".
    empty = Settings(smtp_from_address="", resend_from_address="", alert_webhook_provider="", anthropic_api_key="")

    assert [f for f in check.classify_api(Settings, empty) if f.level != "OK"] == []
    filled = Settings(google_reviews_place_id="place")
    assert _levels(check.classify_api(Settings, filled))["GOOGLE_REVIEWS_PLACE_ID"] == "WARN"


def test_env_example_is_clean(tmp_path):
    completed = subprocess.run(
        [sys.executable, SCRIPT, "--studio-dir", str(tmp_path)],
        env={
            **{k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "ENVIRONMENT", "VITE_API_URL")},
            "GWA_ENV_FILE": os.path.join(API_ROOT, ".env.example"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[WARN]" not in completed.stdout and "[UNSAFE]" not in completed.stdout
    assert "Verdict: safe for local services." in completed.stdout


@pytest.mark.parametrize(
    ("database_url", "level"),
    [
        (f"postgresql+psycopg://user:{FAKE_SECRET}@{REMOTE_HOST}:5432/app", "UNSAFE"),
        (f"postgresql://user:{FAKE_SECRET}@127.0.0.1/app", "OK"),
        (f"postgresql+psycopg://user:{FAKE_SECRET}@postgres:5432/app", "OK"),  # the compose service
        ("sqlite:///./dev.db", "OK"),
        ("not a url at all", "UNSAFE"),
    ],
)
def test_the_database_is_classified_by_host(database_url, level):
    finding = check._classify_database(database_url)

    assert finding.level == level
    assert FAKE_SECRET not in finding.detail and REMOTE_HOST not in finding.detail


def test_production_credentials_are_unsafe_and_reported_by_name_only():
    leaked = Settings(
        environment="production",
        anthropic_api_key=FAKE_SECRET,
        r2_secret_access_key=FAKE_SECRET,
        n8n_base_url=f"https://{REMOTE_HOST}",
        n8n_api_key=FAKE_SECRET,
        higgsfield_cli_enabled=True,
    )

    findings = check.classify_api(Settings, leaked)

    levels = _levels(findings)
    for name in ("ENVIRONMENT", "ANTHROPIC_API_KEY", "R2_SECRET_ACCESS_KEY", "N8N_BASE_URL", "N8N_API_KEY"):
        assert levels[name] == "UNSAFE", name
    assert levels["HIGGSFIELD_CLI_ENABLED"] == "UNSAFE"
    assert all(FAKE_SECRET not in f.detail and REMOTE_HOST not in f.detail for f in findings)


def test_studio_dev_mode_prefers_the_development_local_file(tmp_path):
    (tmp_path / ".env.local").write_text(f"VITE_API_URL=https://{REMOTE_HOST}\n")
    assert check.studio_dev_api(str(tmp_path), {}).level == "UNSAFE"

    (tmp_path / ".env.development.local").write_text("VITE_API_URL=http://localhost:8000\n")
    finding = check.studio_dev_api(str(tmp_path), {})

    assert finding.level == "OK" and ".env.development.local" in finding.detail
    assert check.studio_dev_api(str(tmp_path), {"VITE_API_URL": f"https://{REMOTE_HOST}"}).level == "UNSAFE"
    assert REMOTE_HOST not in finding.detail


def test_the_script_never_prints_a_value(tmp_path):
    env_file = tmp_path / "fake.env"
    env_file.write_text(
        f"DATABASE_URL=postgresql+psycopg://user:{FAKE_SECRET}@{REMOTE_HOST}:5432/app\n"
        f"ANTHROPIC_API_KEY={FAKE_SECRET}\n"
    )
    studio = tmp_path / "studio"
    studio.mkdir()
    environ = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "ENVIRONMENT", "VITE_API_URL")}

    completed = subprocess.run(
        [sys.executable, SCRIPT, "--studio-dir", str(studio)],
        env={**environ, "GWA_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "[UNSAFE] DATABASE_URL: postgresql, remote host" in output
    assert "[UNSAFE] ANTHROPIC_API_KEY" in output
    assert FAKE_SECRET not in output and REMOTE_HOST not in output


def test_invalid_values_are_reported_by_name_only(tmp_path):
    env_file = tmp_path / "fake.env"
    env_file.write_text(f"SMTP_PORT={FAKE_SECRET}\n")
    environ = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "ENVIRONMENT")}

    completed = subprocess.run(
        [sys.executable, SCRIPT, "--studio-dir", str(tmp_path)],
        env={**environ, "GWA_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 2, output
    assert "SMTP_PORT" in output and FAKE_SECRET not in output
