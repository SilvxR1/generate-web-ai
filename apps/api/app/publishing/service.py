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

P2 continuation: a published site's contact form is never wired to
n8n's webhook directly anymore — every site (deterministic or
generative) always submits through
POST /public/businesses/{id}/leads (app.routers.public), which
dispatches to an active n8n automation itself, server-side, strictly
after persisting the Lead. See app.automation.n8n.dispatch's own
docstring for the full "why"; this module no longer touches
`site_config`'s contact-form `action` at all.
"""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.creative.frontend_engine.build import rebuild_from_archive
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.website import Website
from app.db.models.website_version import WebsiteVersion
from app.domain.enums import DeployTarget, WebsiteStatus
from app.publishing.build import build_site
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsitePublisher
from app.repositories.website import WebsiteRepository
from app.schemas.site_config import SiteConfigPayload
from app.storage import StorageProvider


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


def website_project_name(business_id: UUID) -> str:
    """The Cloudflare Pages project name (WebsitePublisher's `site_id`)
    a business's website lives under — computed once here so
    app.publishing.domains (which needs the same identifier to attach a
    custom domain to the right project) never derives its own, possibly
    drifting, copy of this format."""
    return f"site-{business_id.hex}"


def _to_state_result(website: Website) -> WebsiteStateResult:
    return WebsiteStateResult(
        status=website.status,
        live_url=website.deploy_url,
        deployment_id=website.provider_deployment_id,
        deployed_at=website.deployed_at,
        updated_at=website.updated_at,
    )


def publish_website(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    site_config: SiteConfigPayload,
    publisher: WebsitePublisher,
) -> WebsiteStateResult:
    """`publisher` is already-validated-as-configured (see
    app.dependencies.get_website_publisher) and injected rather than
    built here, so tests can pass one wired to a mocked transport
    without needing real hosting-provider credentials.

    Every publish attempt is a fresh deploy — there's no "already
    published, no-op" short-circuit like activation's (a republish is
    exactly how a business owner pushes updated content live), but a
    failure only ever flips `status` to FAILED; it never touches
    `deploy_url`/`provider_deployment_id`/`deployed_at`, so a site that
    was live before a failed republish attempt is still reported live.
    """
    repo = WebsiteRepository(session)
    website = repo.get_by_business(tenant_id, business_id)
    # Same "the generated static site needs to know its own business id"
    # reasoning as app.publishing.drafts.create_website_draft — set again
    # here (idempotent if already set) so a direct publish that never
    # went through the draft flow still gets it. Never trusted from the
    # payload itself.
    site_config.businessId = str(business_id)
    site_id = website_project_name(business_id)

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

    # One immutable, append-only snapshot per successful publish (P0
    # Phase 20-22) — including a republish a rollback itself performs
    # (app.publishing.versions.rollback_to_version calls this same
    # function), so version history accumulates through the one publish
    # path rather than a second, parallel bookkeeping mechanism.
    #
    # Flushed as its own isolated unit (`flush([version])`, not a plain
    # `flush()`) so this new row is immediately queryable by a caller in
    # the same session/transaction (e.g. list_website_versions called
    # right after publish_website in a test) without also flushing
    # `website`'s own still-pending UPDATE — TimestampMixin.updated_at's
    # `onupdate=func.now()` makes a flush of that row trigger a refresh
    # of its attributes from the DB, and SQLite's DateTime(timezone=True)
    # doesn't actually round-trip tzinfo, which would silently turn the
    # aware `website.deployed_at` this function just set into a naive
    # one before this function even returns.
    version = WebsiteVersion(
        tenant_id=tenant_id,
        business_id=business_id,
        website_id=website.id,
        site_config=site_config.model_dump(mode="json"),
        deploy_url=str(published.url),
        provider_deployment_id=published.deployment_id,
        published_at=website.deployed_at,
    )
    session.add(version)
    session.flush([version])

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


def publish_generative_website(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    artifact_row: GenerativeWebsiteArtifact,
    publisher: WebsitePublisher,
    storage: StorageProvider,
    api_base_url: str | None = None,
) -> WebsiteStateResult:
    """The GENERATIVE counterpart to publish_website above. Rebuilds
    from the durably-archived generative source
    (app.creative.frontend_engine.build.rebuild_from_archive) rather than
    re-invoking the AI Frontend Engineer — "what was approved is what
    gets published" holds here the same way it does for the
    deterministic path's re-run of build_site, just against a fixed
    source tree instead of a fixed SiteConfig. Persists the identical
    Website/WebsiteVersion rows the deterministic path does; `config`
    stores a small generative marker (never a fabricated SiteConfig)
    since there is no SiteConfig for a generative build."""
    repo = WebsiteRepository(session)
    website = repo.get_by_business(tenant_id, business_id)
    site_id = website_project_name(business_id)
    direction_id = artifact_row.creative_direction_id
    config_snapshot = {
        "engine": "generative",
        "creative_direction_id": str(direction_id) if direction_id else None,
        "generator_provider": artifact_row.generator_provider,
        "generator_model": artifact_row.generator_model,
        "workspace_key": artifact_row.workspace_key,
    }

    try:
        archive = storage.load(artifact_row.workspace_key)
        artifact = rebuild_from_archive(archive, business_id=str(business_id), api_base_url=api_base_url)
        published = publisher.publish(site_id=site_id, artifact=artifact)
    except WebsitePublisherError as exc:
        if website is None:
            website = Website(
                tenant_id=tenant_id,
                business_id=business_id,
                deploy_target=DeployTarget.CLOUDFLARE,
                status=WebsiteStatus.FAILED,
                config=config_snapshot,
            )
            repo.add(website)
        else:
            website.status = WebsiteStatus.FAILED
            website.config = config_snapshot
        raise WebsitePublishError(
            f"Publishing this generative website failed: {exc}",
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
    website.config = config_snapshot

    version = WebsiteVersion(
        tenant_id=tenant_id,
        business_id=business_id,
        website_id=website.id,
        site_config=config_snapshot,
        deploy_url=str(published.url),
        provider_deployment_id=published.deployment_id,
        published_at=website.deployed_at,
    )
    session.add(version)
    session.flush([version])

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
