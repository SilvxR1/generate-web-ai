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

import hashlib
import logging
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from pydantic import AnyHttpUrl

from app.publishing.build import SITE_BUILDER_DIR
from app.publishing.cloudflare.client import CloudflarePagesClient
from app.publishing.cloudflare.client import validate_project_name as _validate_project_name
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import (
    PreviewDeployment,
    PreviewPublisher,
    PublishedSite,
    WebsiteArtifact,
    WebsitePublisher,
)

logger = logging.getLogger(__name__)

# Deployment ids we return are "<project_name>::<cloudflare_deployment_id>"
# — get_status needs both (which project, which deployment) and
# WebsitePublisher's contract treats this string as opaque to every
# other layer, so a composite key stays entirely internal to this module.
_DEPLOYMENT_ID_SEPARATOR = "::"

_WRANGLER_TIMEOUT_SECONDS = 120
_PRODUCTION_BRANCH = "production"


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
            _wrangler_deploy(
                project_name, out_dir, branch=_PRODUCTION_BRANCH, account_id=self._account_id, api_token=self._api_token
            )

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

    def _url_for(self, project_name: str) -> AnyHttpUrl:
        # The project's own stable production alias — not a
        # per-deployment preview URL (those change every publish), so a
        # business's public "live URL" stays constant across republishes.
        return AnyHttpUrl(f"https://{project_name}.pages.dev")


# --- A8.3.4.2a: real draft previews --------------------------------------------

PREVIEW_PROJECT_NAME = "gwa-draft-previews"
# "d-" + 24 hex chars = 96 bits from SHA-256(draft UUID): deterministic per
# draft, unguessable without the draft id, and short enough to stay a
# single Pages branch-alias label.
_PREVIEW_BRANCH_PATTERN = re.compile(r"^d-[0-9a-f]{24}$")
_PLACEHOLDER_HTML = (
    b"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=robots content=noindex>"
    b"<title>Nothing here</title></head><body><p>Nothing here.</p></body></html>\n"
)
_RETIRED_HTML = (
    b"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=robots content=noindex>"
    b"<title>Preview ended</title></head><body><p>This preview has ended.</p></body></html>\n"
)


def preview_branch_for(draft_id: uuid.UUID) -> str:
    """The ONLY way a preview branch is chosen: derived from the draft's
    own id, never from request input — one draft can't target another's
    branch, and the result can never be the production branch."""
    return "d-" + hashlib.sha256(draft_id.bytes).hexdigest()[:24]


def validate_preview_branch(branch: str) -> str:
    if branch == _PRODUCTION_BRANCH or not _PREVIEW_BRANCH_PATTERN.match(branch):
        raise WebsitePublisherError(f"refusing to deploy a preview to branch {branch!r}")
    return branch


class CloudflarePagesPreviewPublisher(PreviewPublisher):
    """Deploys draft previews into ONE dedicated Pages project
    (PREVIEW_PROJECT_NAME) — never a business's `site-<id>` project, so a
    preview can't touch a production alias or custom domain. Each draft
    gets its own non-production branch; Pages serves those as preview
    deployments (X-Robots-Tag: noindex added by the platform, protected by
    the project's Cloudflare Access policy). Same `_materialize` +
    `wrangler pages deploy` path as production: the artifact is deployed
    byte-for-byte, no transformation."""

    def __init__(
        self,
        client: CloudflarePagesClient,
        *,
        account_id: str,
        api_token: str,
        project_name: str = PREVIEW_PROJECT_NAME,
    ) -> None:
        project_name = _validate_project_name(project_name)
        if project_name.startswith("site-"):
            raise WebsitePublisherError("the preview project must not be a business production project")
        self._client = client
        self._account_id = account_id
        self._api_token = api_token
        self._project = project_name

    @property
    def project_name(self) -> str:
        return self._project

    def publish_preview(self, *, branch: str, artifact: WebsiteArtifact) -> PreviewDeployment:
        branch = validate_preview_branch(branch)
        self._ensure_project()
        self._deploy(branch, artifact)
        deployment = self._latest_on_branch(branch)
        if deployment is None:
            raise WebsitePublisherError(
                "wrangler reported a successful preview deploy, but Cloudflare's Pages API shows no deployment "
                "for its branch; refusing to report a preview URL."
            )
        url = str(deployment.get("url") or "")
        host = url.removeprefix("https://").split("/", 1)[0]
        if not url.startswith("https://") or not host.endswith(f".{self._project}.pages.dev"):
            raise WebsitePublisherError("Cloudflare returned an unexpected preview URL; refusing to report it.")
        return PreviewDeployment(deployment_id=str(deployment["id"]), url=AnyHttpUrl(url))

    def retire_preview(self, *, branch: str, deployment_id: str) -> None:
        """Pages can't delete a branch's latest deployment, so the preview
        is first superseded by a tiny "preview ended" page on the same
        branch, then the real deployment is deleted. The tombstone itself
        stays (A8_PREVIEW_CLEANUP_DEBT)."""
        branch = validate_preview_branch(branch)
        latest = self._latest_on_branch(branch)
        if latest is not None and str(latest.get("id")) == deployment_id:
            self._deploy(branch, WebsiteArtifact(files={"index.html": _RETIRED_HTML}))
        self._client.delete_deployment(self._project, deployment_id)

    def delete_superseded(self, deployment_id: str) -> None:
        """Deletes an older (non-latest) preview deployment of this project."""
        self._client.delete_deployment(self._project, deployment_id)

    def _ensure_project(self) -> None:
        self._client.ensure_project(self._project)
        project = self._client.get_project(self._project)
        if not project.get("canonical_deployment") and not project.get("latest_deployment"):
            # A deterministic, harmless root for the preview project — never
            # a customer artifact on its production branch.
            self._deploy(_PRODUCTION_BRANCH, WebsiteArtifact(files={"index.html": _PLACEHOLDER_HTML}))

    def _deploy(self, branch: str, artifact: WebsiteArtifact) -> None:
        with tempfile.TemporaryDirectory(prefix="cf-pages-preview-") as tmp_dir:
            out_dir = Path(tmp_dir)
            _materialize(artifact, out_dir)
            _wrangler_deploy(
                self._project, out_dir, branch=branch, account_id=self._account_id, api_token=self._api_token
            )

    def _latest_on_branch(self, branch: str) -> dict | None:
        for deployment in self._client.list_deployments(self._project):
            trigger = (deployment.get("deployment_trigger") or {}).get("metadata") or {}
            if trigger.get("branch") == branch:
                return deployment
        return None


def _wrangler_deploy(project_name: str, artifact_dir: Path, *, branch: str, account_id: str, api_token: str) -> str:
    # Inheriting the full parent environment (HOME, PATH, npm's own
    # cache/config vars, ...) is deliberate — the two Cloudflare
    # vars are the only ones that need to be set/overridden here;
    # dropping the rest breaks npx/node's own bookkeeping, not just
    # wrangler's auth. No other secret flows through this call.
    env = {
        **os.environ,
        "CLOUDFLARE_ACCOUNT_ID": account_id,
        "CLOUDFLARE_API_TOKEN": api_token,
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
                f"--branch={branch}",
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


def _materialize(artifact: WebsiteArtifact, out_dir: Path) -> None:
    for relative_path, content in artifact.files.items():
        destination = out_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
