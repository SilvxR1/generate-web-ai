"""DEV-1 local environment check: is this machine's configuration safe for
running the API, Alembic and Studio locally?

It loads the API settings exactly as a local `uvicorn`/`alembic` run from
apps/api would (the dotenv file named by GWA_ENV_FILE, default `.env`, plus
the shell environment) and works out Studio's development API the way
`vite` does. It prints CLASSIFICATIONS ONLY: setting names, "loopback" or
"remote", "set" or "unset". Never a URL, host, token, password or other
value, including from validation errors.

    cd apps/api && .venv/bin/python scripts/check_local_env.py

Exit status: 0 when nothing is UNSAFE, 1 otherwise, 2 when the settings
cannot be loaded. Read-only: it opens no connection and writes nothing.
"""

import argparse
import ipaddress
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

API_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
STUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(API_ROOT)), "apps", "studio")

# Production or paid-provider credentials: any value is unsafe for local work.
PROVIDER_CREDENTIALS = (
    "anthropic_api_key",
    "higgsfield_api_key",
    "higgsfield_api_key_id",
    "higgsfield_api_key_secret",
    "cloudflare_account_id",
    "cloudflare_api_token",
    "r2_account_id",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket_name",
    "r2_public_base_url",
    "r2_private_bucket_name",
    "r2_private_access_key_id",
    "r2_private_secret_access_key",
    "resend_api_key",
    "google_reviews_api_key",
    "alert_webhook_url",
)
# Endpoints that are fine on loopback (a local n8n, a local mail catcher, this
# API) and unsafe anywhere else. Their credentials follow the endpoint.
LOCAL_ENDPOINTS = {
    "n8n_base_url": ("n8n_api_key",),
    "smtp_host": ("smtp_username", "smtp_password"),
    "internal_api_base_url": (),
}
# Secrets that local work may need, but only as local-only values.
LOCAL_ONLY_SECRETS = (
    "credential_encryption_key",
    "internal_automation_token",
    "n8n_internal_automation_credential_id",
    "generation_worker_token_sha256",
    "generation_worker_signing_key",
)
PAID_GATES = ("higgsfield_cli_enabled",)
INFO_GATES = (
    "generative_website_builds_enabled",
    "supervised_source_imports_enabled",
    "legacy_tenant_header_auth_enabled",
)
# Hosts that only exist inside the local docker-compose network.
COMPOSE_HOSTS = frozenset({"postgres", "backend", "n8n"})


@dataclass(frozen=True)
class Finding:
    level: str  # OK | INFO | WARN | UNSAFE
    subject: str
    detail: str


def host_class(host: str | None) -> str:
    if host is None or host == "":
        return "loopback"
    host = host.strip("[]").split("%", 1)[0].lower()
    if host in ("localhost", "ip6-localhost") or host.endswith(".localhost"):
        return "loopback"
    if host in COMPOSE_HOSTS:
        return "compose"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "remote"
    mapped = getattr(address, "ipv4_mapped", None)
    return "loopback" if (mapped or address).is_loopback else "remote"


def url_host_class(value: str) -> str:
    try:
        parts = urlsplit(value if "//" in value else f"//{value}")
        return host_class(parts.hostname)
    except ValueError:
        return "unparseable"


def classify_api(settings_cls: type, settings: object) -> list[Finding]:
    findings: list[Finding] = []

    environment = settings.environment
    if environment == "production":
        findings.append(Finding("UNSAFE", "ENVIRONMENT", "production"))
    else:
        label = "development" if environment == "development" else "non-production"
        findings.append(Finding("OK", "ENVIRONMENT", label))

    findings.append(_classify_database(settings.database_url))

    for name in PROVIDER_CREDENTIALS:
        if getattr(settings, name):
            findings.append(Finding("UNSAFE", name.upper(), "set (production or paid-provider credential)"))

    for name, credentials in LOCAL_ENDPOINTS.items():
        value = getattr(settings, name)
        if not value:
            continue
        where = url_host_class(value) if name.endswith("_url") else host_class(value)
        level = "OK" if where in ("loopback", "compose") else "UNSAFE"
        findings.append(Finding(level, name.upper(), where))
        for credential in credentials:
            if getattr(settings, credential):
                findings.append(Finding(level, credential.upper(), f"set (for a {where} endpoint)"))

    for name in LOCAL_ONLY_SECRETS:
        if getattr(settings, name):
            findings.append(Finding("WARN", name.upper(), "set: must be a local-only value, never production's"))

    for name in PAID_GATES:
        if getattr(settings, name):
            findings.append(Finding("UNSAFE", name.upper(), "enabled (calls a paid provider)"))
    for name in INFO_GATES:
        if getattr(settings, name):
            findings.append(Finding("INFO", name.upper(), "enabled"))

    for origin in settings.cors_origins:
        if url_host_class(origin) != "loopback":
            findings.append(Finding("WARN", "CORS_ORIGINS", "includes a non-loopback origin"))
            break

    classified = {"environment", "database_url", "cors_origins", *PROVIDER_CREDENTIALS, *LOCAL_ONLY_SECRETS}
    classified |= {*LOCAL_ENDPOINTS, *(c for cs in LOCAL_ENDPOINTS.values() for c in cs), *PAID_GATES, *INFO_GATES}
    for name, field in settings_cls.model_fields.items():
        if name in classified or field.default is not None:
            continue
        if getattr(settings, name):  # an empty `KEY=` line in the env file means unset
            findings.append(Finding("WARN", name.upper(), "set (not classified by this check)"))
    return findings


def _classify_database(database_url: str) -> Finding:
    from sqlalchemy.engine import make_url

    try:
        url = make_url(database_url)
    except Exception:  # the message would echo the URL
        return Finding("UNSAFE", "DATABASE_URL", "unparseable")
    backend = url.get_backend_name()
    if backend == "sqlite":
        return Finding("OK", "DATABASE_URL", "sqlite (local file or in-memory)")
    where = host_class(url.host)
    level = "OK" if where in ("loopback", "compose") else "UNSAFE"
    return Finding(level, "DATABASE_URL", f"{backend}, {where} host")


def studio_dev_api(studio_dir: str, environ: Mapping[str, str]) -> Finding:
    """VITE_API_URL as `vite` (mode development) resolves it: the shell first,
    then .env.development.local > .env.development > .env.local > .env."""
    subject = "Studio dev VITE_API_URL"
    if environ.get("VITE_API_URL"):
        source, value = "shell", environ["VITE_API_URL"]
    else:
        source, value = None, None
        for name in (".env.development.local", ".env.development", ".env.local", ".env"):
            found = _read_vite_api_url(os.path.join(studio_dir, name))
            if found is not None:
                source, value = name, found
                break
    if value is None:
        return Finding("OK", subject, "unset (code default http://localhost:8000)")
    where = url_host_class(value)
    return Finding("OK" if where == "loopback" else "UNSAFE", subject, f"{where} (from {source})")


def _read_vite_api_url(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    found = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if line.startswith("VITE_API_URL="):
                found = line.split("=", 1)[1].strip().strip("'\"")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--studio-dir", default=STUDIO_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    os.chdir(API_ROOT)  # the dotenv path is relative to apps/api, as for uvicorn/alembic
    sys.path.insert(0, API_ROOT)
    env_file = os.environ.get("GWA_ENV_FILE", ".env")
    print("GWA local environment check: classifications only, no values are shown.")
    if not env_file:
        print("[INFO] env file: disabled (GWA_ENV_FILE is empty); shell environment only")
    else:
        state = "present" if os.path.isfile(env_file) else "absent"
        print(f"[INFO] env file: {os.path.basename(env_file)} ({state})")

    from pydantic import ValidationError

    try:
        from app.config import Settings, settings
    except ValidationError as exc:  # its message would echo the invalid values
        names = sorted({".".join(str(part) for part in error["loc"]).upper() for error in exc.errors()})
        print(f"[UNSAFE] settings: invalid values for {', '.join(names)} (values not shown)")
        return 2
    except Exception as exc:
        print(f"[UNSAFE] settings: could not be loaded ({type(exc).__name__})")
        return 2

    findings = [*classify_api(Settings, settings), studio_dev_api(args.studio_dir, os.environ)]
    for finding in findings:
        print(f"[{finding.level}] {finding.subject}: {finding.detail}")
    unsafe = [f for f in findings if f.level == "UNSAFE"]
    print(
        f"Verdict: UNSAFE ({len(unsafe)} finding(s)). Do not start local services."
        if unsafe
        else "Verdict: safe for local services."
    )
    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
