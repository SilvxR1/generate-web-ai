"""CloudflarePagesPublisher — the first, replaceable WebsitePublisher
implementation. Nothing outside this module (and client.py) knows
Cloudflare exists — callers depend on WebsitePublisher.

Publishes a WebsiteArtifact (a real Astro build's files — see
app.publishing.build) as a Cloudflare Pages deployment. Pages, not
Workers: a real Astro build is index.html plus one or more separate
hashed CSS/JS files, and Cloudflare Pages serves a directory of static
files with correct content-types natively.

The actual upload is delegated to `wrangler pages deploy` (a subprocess,
same shape as app.publishing.build's `astro build` call), not this
codebase's own REST calls: a hand-rolled raw-REST direct-upload
implementation (upload-token JWT + check-missing + upload + upsert-
hashes) was built and confirmed live against a real Cloudflare account —
every one of those calls reported success, Cloudflare's own API agreed
the deployment and every asset were present, and the live URL still
500'd on every request with no further diagnostic surface available.
Cloudflare's own guidance is to use Wrangler for direct-upload of
prebuilt assets, so that's what this does now. CloudflarePagesClient
(client.py) is kept for what the REST API *is* reliable for: project
existence/creation and reading status back after the fact — never for
uploading file content.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from pydantic import AnyHttpUrl

from app.publishing.build import SITE_BUILDER_DIR
from app.publishing.cloudflare.client import CloudflarePagesClient
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher

# Deployment ids we return are "<project_name>::<cloudflare_deployment_id>"
# — get_status needs both (which project, which deployment) and
# WebsitePublisher's contract treats this string as opaque to every
# other layer, so a composite key stays entirely internal to this module.
_DEPLOYMENT_ID_SEPARATOR = "::"

_PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,56}$")

_WRANGLER_TIMEOUT_SECONDS = 120


def _validate_project_name(site_id: str) -> str:
    if not _PROJECT_NAME_PATTERN.match(site_id):
        raise WebsitePublisherError(
            f"{site_id!r} is not a valid Cloudflare Pages project name "
            "(lowercase letters, digits, hyphens; 1-57 chars; can't start with a hyphen)."
        )
    return site_id


class CloudflarePagesPublisher(WebsitePublisher):
    def __init__(self, client: CloudflarePagesClient, *, account_id: str, api_token: str) -> None:
        self._client = client
        # Passed to the `wrangler` subprocess as env vars (its own
        # documented non-interactive auth path) — never written to
        # disk, never logged, never part of any command-line argument.
        self._account_id = account_id
        self._api_token = api_token

    def publish(self, *, site_id: str, artifact: WebsiteArtifact) -> PublishedSite:
        project_name = _validate_project_name(site_id)

        self._client.ensure_project(project_name)

        with tempfile.TemporaryDirectory(prefix="cf-pages-deploy-") as tmp_dir:
            out_dir = Path(tmp_dir)
            _materialize(artifact, out_dir)
            self._wrangler_deploy(project_name, out_dir)

        # wrangler's own stdout already confirms success/failure (a
        # non-zero exit raises before this point); this is the
        # provider-neutral status check the rest of this codebase
        # trusts — same call get_status uses.
        project = self._client.get_project(project_name)
        deployment_id = (project.get("latest_deployment") or {}).get("id")
        if not deployment_id:
            raise WebsitePublisherError(
                "wrangler reported a successful deploy, but Cloudflare's Pages API shows no "
                "deployment for this project; refusing to report this as published."
            )

        return PublishedSite(
            deployment_id=f"{project_name}{_DEPLOYMENT_ID_SEPARATOR}{deployment_id}",
            url=self._url_for(project_name),
            live=True,
        )

    def get_status(self, deployment_id: str) -> PublishedSite:
        project_name, _, _cf_deployment_id = deployment_id.partition(_DEPLOYMENT_ID_SEPARATOR)
        project_name = _validate_project_name(project_name)

        project = self._client.get_project(project_name)
        return PublishedSite(
            deployment_id=deployment_id,
            url=self._url_for(project_name),
            live=project.get("latest_deployment") is not None,
        )

    def unpublish(self, deployment_id: str) -> None:
        """Deletes the whole Cloudflare Pages project `deployment_id`
        names (see client.py's delete_project docstring for why "whole
        project" rather than "just this deployment") — the site's
        pages.dev URL genuinely stops resolving. Idempotent via
        CloudflarePagesClient.delete_project: calling this twice, or
        calling it for a project that was never actually created, never
        raises."""
        project_name, _, _cf_deployment_id = deployment_id.partition(_DEPLOYMENT_ID_SEPARATOR)
        project_name = _validate_project_name(project_name)
        self._client.delete_project(project_name)

    def _wrangler_deploy(self, project_name: str, artifact_dir: Path) -> str:
        # Inheriting the full parent environment (HOME, PATH, npm's own
        # cache/config vars, ...) is deliberate — the two Cloudflare
        # vars are the only ones that need to be set/overridden here;
        # dropping the rest breaks npx/node's own bookkeeping, not just
        # wrangler's auth. No other secret flows through this call.
        env = {
            **os.environ,
            "CLOUDFLARE_ACCOUNT_ID": self._account_id,
            "CLOUDFLARE_API_TOKEN": self._api_token,
            "CI": "true",
        }
        try:
            result = subprocess.run(
                [
                    "npx",
                    "wrangler",
                    "pages",
                    "deploy",
                    str(artifact_dir),
                    f"--project-name={project_name}",
                    # Without this, wrangler infers the deploy branch
                    # from whatever git repo happens to contain `cwd`
                    # (this monorepo, e.g. "main") — confirmed live: that
                    # produced a "preview" deployment (branch != the
                    # project's own production_branch), served fine at
                    # its own per-deployment URL but never aliased at
                    # the stable https://{project}.pages.dev/ this
                    # codebase persists as the business's live URL.
                    "--branch=production",
                ],
                cwd=SITE_BUILDER_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=_WRANGLER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise WebsitePublisherError(f"wrangler pages deploy timed out after {_WRANGLER_TIMEOUT_SECONDS}s") from exc
        except OSError as exc:
            raise WebsitePublisherError(f"could not run wrangler: {exc}") from exc

        if result.returncode != 0:
            raise WebsitePublisherError(
                f"wrangler pages deploy failed (exit {result.returncode}): {_tail(result.stdout + result.stderr)}"
            )
        return result.stdout

    def _url_for(self, project_name: str) -> AnyHttpUrl:
        # The project's own stable production alias — not a
        # per-deployment preview URL (those change every publish), so a
        # business's public "live URL" stays constant across republishes.
        return AnyHttpUrl(f"https://{project_name}.pages.dev")


def _materialize(artifact: WebsiteArtifact, out_dir: Path) -> None:
    for relative_path, content in artifact.files.items():
        destination = out_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
