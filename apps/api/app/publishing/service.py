"""BusinessConfig -> generateSiteConfig() (computed once, client-side —
the same call Studio's own website preview uses) -> a real, live static
site, with its deployment state persisted in
app.db.models.website.Website. Publish is always an explicit,
human-triggered action (POST .../website/publish, see
app.routers.businesses) — this module never runs on its own after
analysis or business creation, and a failed publish attempt never
touches `deploy_url`/`deployed_at`: only a successful deploy advances
those, so a previous live site is never reported gone just because a
later republish attempt failed.

If the site has a lead-capture contact form and this business already
has an active automation, `_inject_lead_capture_webhook_url` wires that
automation's real n8n webhook URL into the form's `action` before the
build — see that function's docstring for exactly when it does (and
deliberately doesn't) do that.
"""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.automation.n8n import lead_submitted_webhook_url
from app.db.models.website import Website
from app.db.models.workflow import Workflow
from app.domain.enums import DeployTarget, WebsiteStatus, WorkflowStatus
from app.publishing.build import build_site
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsitePublisher
from app.repositories.website import WebsiteRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.site_config import SiteConfigPayload


class WebsitePublishError(Exception):
    """Raised for every "can't publish, and here's exactly why" case —
    currently just the hosting provider call itself failing (including
    "not configured"). app.routers.businesses maps `code`/`status_code`
    straight onto the HTTP response; never a bare 500."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class WebsiteStateResult(BaseModel):
    """Provider-neutral snapshot of a business's *persisted* deployment
    state (app.db.models.website.Website) — no provider-specific
    payload, no credential of any kind. What publish and the read-only
    GET endpoint both return, so Studio can treat this — not its own
    component state — as the source of truth."""

    model_config = ConfigDict(extra="forbid")

    status: WebsiteStatus
    live_url: str | None
    deployment_id: str | None
    deployed_at: datetime | None
    updated_at: datetime | None


def _to_state_result(website: Website) -> WebsiteStateResult:
    return WebsiteStateResult(
        status=website.status,
        live_url=website.deploy_url,
        deployment_id=website.provider_deployment_id,
        deployed_at=website.deployed_at,
        updated_at=website.updated_at,
    )


def _inject_lead_capture_webhook_url(
    site_config: SiteConfigPayload, *, workflow: Workflow | None, n8n_base_url: str | None
) -> None:
    """Wires the real n8n webhook URL into the contact form's `action`,
    mutating `site_config` in place — only when everything needed for
    that URL to be real actually exists: N8N_BASE_URL is configured
    *and* a matching lead-capture Workflow has already been activated
    for this business (app.db.models.workflow.Workflow, status ACTIVE
    — see app.automation.activation, the only code that sets it).

    Never fabricates a URL: when either is missing, the form is left
    exactly as `generateSiteConfig()` produced it — no `action` — which
    is Contact.astro's existing, documented "not wired to a backend
    yet" behavior. Publishing itself still succeeds either way: a site
    with lead capture configured but automation not yet activated is a
    normal, valid state in this architecture (the two are independent,
    explicit human actions), not a publish-time error.
    """
    if not n8n_base_url or workflow is None or workflow.status is not WorkflowStatus.ACTIVE:
        return

    webhook_url = lead_submitted_webhook_url(n8n_base_url, workflow.local_workflow_id)
    for page in site_config.pages:
        for block in page.blocks:
            if block.type == "contact" and isinstance(block.content.get("form"), dict):
                block.content["form"]["action"] = webhook_url


def publish_website(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    site_config: SiteConfigPayload,
    publisher: WebsitePublisher,
    n8n_base_url: str | None = None,
) -> WebsiteStateResult:
    """`publisher` is already-validated-as-configured (see
    app.dependencies.get_website_publisher) and injected rather than
    built here, so tests can pass one wired to a mocked transport
    without needing real hosting-provider credentials. `n8n_base_url`
    is passed the same way (see app.routers.businesses) purely to wire
    the lead-capture webhook URL below — this module never reaches into
    global settings itself.

    Every publish attempt is a fresh deploy — there's no "already
    published, no-op" short-circuit like activation's (a republish is
    exactly how a business owner pushes updated content live), but a
    failure only ever flips `status` to FAILED; it never touches
    `deploy_url`/`provider_deployment_id`/`deployed_at`, so a site that
    was live before a failed republish attempt is still reported live.
    """
    repo = WebsiteRepository(session)
    website = repo.get_by_business(tenant_id, business_id)
    workflow = WorkflowRepository(session).get_for_business(tenant_id, business_id)
    _inject_lead_capture_webhook_url(site_config, workflow=workflow, n8n_base_url=n8n_base_url)
    site_id = f"site-{business_id.hex}"

    try:
        artifact = build_site(site_config)
        published = publisher.publish(site_id=site_id, artifact=artifact)
    except WebsitePublisherError as exc:
        if website is None:
            website = Website(
                tenant_id=tenant_id,
                business_id=business_id,
                deploy_target=DeployTarget.CLOUDFLARE,
                status=WebsiteStatus.FAILED,
                config=site_config.model_dump(mode="json"),
            )
            repo.add(website)
        else:
            website.status = WebsiteStatus.FAILED
            website.config = site_config.model_dump(mode="json")
        raise WebsitePublishError(
            f"Publishing this website failed: {exc}",
            code="website_publish_failed",
            status_code=502,
        ) from exc

    if website is None:
        website = Website(tenant_id=tenant_id, business_id=business_id)
        repo.add(website)

    website.deploy_target = DeployTarget.CLOUDFLARE
    website.status = WebsiteStatus.LIVE
    website.deploy_url = str(published.url)
    website.provider_deployment_id = published.deployment_id
    website.deployed_at = datetime.now(UTC)
    website.config = site_config.model_dump(mode="json")

    return _to_state_result(website)


def unpublish_website(
    *, session: Session, tenant_id: UUID, business_id: UUID, publisher: WebsitePublisher
) -> WebsiteStateResult:
    """The counterpart to publish_website: takes a *currently live* site
    down for real via `publisher.unpublish` (never just a local status
    flip — see WebsitePublisher.unpublish's own docstring), then marks
    it INACTIVE and clears `deploy_url`/`provider_deployment_id` — once
    the site is actually gone, persisting a stale live URL would be
    exactly the kind of "simulated success" this codebase's read
    endpoints elsewhere are careful never to produce.

    Same idempotent shape as deactivate_lead_capture_automation
    (app.automation.activation): nothing persisted at all -> raises (a
    website that was never published has nothing to unpublish); already
    INACTIVE/DRAFT/FAILED -> no-op, returns the current state unchanged
    without calling the provider again. Only a currently-LIVE website
    reaches the provider call.
    """
    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    if website is None:
        raise WebsitePublishError(
            "This business has never been published — nothing to deactivate.",
            code="website_not_published",
            status_code=404,
        )

    if website.status is not WebsiteStatus.LIVE:
        return _to_state_result(website)

    try:
        publisher.unpublish(website.provider_deployment_id or "")
    except WebsitePublisherError as exc:
        raise WebsitePublishError(
            f"Deactivating this website failed: {exc}",
            code="website_unpublish_failed",
            status_code=502,
        ) from exc

    website.status = WebsiteStatus.INACTIVE
    website.deploy_url = None
    website.provider_deployment_id = None

    return _to_state_result(website)


def get_website_state(*, session: Session, tenant_id: UUID, business_id: UUID) -> WebsiteStateResult | None:
    """Read-only, provider-neutral, never touches the hosting provider.
    Returns None (not an error) when this business has never been
    published — a legitimate "still just a preview" state, the same
    convention as the workflow/automation read endpoints."""
    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    if website is None:
        return None
    return _to_state_result(website)
