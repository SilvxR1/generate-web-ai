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

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.website import Website
from app.db.models.website_version import WebsiteVersion
from app.domain.business_config import BusinessConfig
from app.domain.enums import DeployTarget, WebsiteStatus
from app.publishing.artifact_store import short_hash
from app.publishing.build import build_site
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsiteArtifact, WebsitePublisher
from app.qa.platform_contract import validate_platform_contract
from app.repositories.website import WebsiteRepository
from app.schemas.site_config import SiteConfigPayload

logger = logging.getLogger(__name__)


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


def _enforce_platform_contract(files: dict[str, bytes], business_config: BusinessConfig) -> None:
    result = validate_platform_contract(files, business_config=business_config)
    if not result.passed:
        # WebsitePublishError, not WebsitePublisherError: deliberately
        # outside publish_website's pipeline-failure handler below, which
        # would otherwise mark the (still live) Website row FAILED.
        raise WebsitePublishError(
            "PlatformContract violation(s): " + "; ".join(f.message for f in result.blocking_violations),
            code="platform_contract_violation",
            status_code=422,
        )


def publish_website(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    site_config: SiteConfigPayload,
    publisher: WebsitePublisher,
    business_config: BusinessConfig | None = None,
) -> WebsiteStateResult:
    """`publisher` is already-validated-as-configured (see
    app.dependencies.get_website_publisher) and injected rather than
    built here, so tests can pass one wired to a mocked transport
    without needing real hosting-provider credentials.

    A8.1.2: when `business_config` is given (the direct
    POST .../website/publish route), the freshly built artifact is held
    to the same app.qa.platform_contract gate create_website_draft
    applies, *before* the hosting provider is called — a BLOCKING
    violation raises WebsitePublishError(code="platform_contract_violation")
    and leaves the Website row (and whatever is live) completely
    untouched: nothing was deployed, so nothing is marked FAILED.
    Optional (not required) because the other caller doesn't need a
    second gate: versions.rollback_to_version republishes a
    previously-live snapshot — an emergency restore that must stay
    possible even for a snapshot published before this gate existed.

    A8.3.4.1: WebsiteDraft publishing no longer comes through here — it
    promotes the draft's stored, already-validated artifact via
    publish_prebuilt_artifact below and never rebuilds. This function
    (a fresh build from a SiteConfig) remains only for the direct
    publish route and version rollback.

    Every publish attempt is a fresh deploy — there's no "already
    published, no-op" short-circuit like activation's (a republish is
    exactly how a business owner pushes updated content live), but a
    failure only ever flips `status` to FAILED; it never touches
    `deploy_url`/`provider_deployment_id`/`deployed_at`, so a site that
    was live before a failed republish attempt is still reported live.
    """
    # Same "the generated static site needs to know its own business id"
    # reasoning as app.publishing.drafts.create_website_draft — set again
    # here (idempotent if already set) so a direct publish that never
    # went through the draft flow still gets it. Never trusted from the
    # payload itself.
    site_config.businessId = str(business_id)

    def _build() -> WebsiteArtifact:
        artifact = build_site(site_config)
        if business_config is not None:
            _enforce_platform_contract(artifact.files, business_config)
        return artifact

    return _deploy_and_record(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        publisher=publisher,
        config=site_config.model_dump(mode="json"),
        produce_artifact=_build,
    )


def publish_prebuilt_artifact(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    artifact: WebsiteArtifact,
    config: dict,
    publisher: WebsitePublisher,
    source_website_draft_id: UUID,
    artifact_sha256: str,
) -> WebsiteStateResult:
    """A8.3.4.1 build once / promote: deploys an already-built,
    already-validated and already-integrity-verified WebsiteArtifact
    (app.publishing.drafts loads it via app.publishing.artifact_store)
    through the exact same WebsitePublisher and Website/WebsiteVersion
    bookkeeping publish_website uses — never calls build_site. The
    resulting WebsiteVersion records which draft and which artifact hash
    it came from. `config` is what Website.config/WebsiteVersion.site_config
    store: the draft's SiteConfig (deterministic) or the generative marker."""
    logger.info(
        "website_publish_from_artifact draft=%s business=%s sha256=%s",
        source_website_draft_id,
        business_id,
        short_hash(artifact_sha256),
    )
    return _deploy_and_record(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        publisher=publisher,
        config=config,
        produce_artifact=lambda: artifact,
        source_website_draft_id=source_website_draft_id,
        artifact_sha256=artifact_sha256,
    )


def _deploy_and_record(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    publisher: WebsitePublisher,
    config: dict,
    produce_artifact: Callable[[], WebsiteArtifact],
    source_website_draft_id: UUID | None = None,
    artifact_sha256: str | None = None,
) -> WebsiteStateResult:
    repo = WebsiteRepository(session)
    website = repo.get_by_business(tenant_id, business_id)
    site_id = website_project_name(business_id)

    try:
        artifact = produce_artifact()
        published = publisher.publish(site_id=site_id, artifact=artifact)
    except WebsitePublisherError as exc:
        # One choke point for every publish-pipeline failure (A6.1):
        # build_site raises SiteBuildError, publisher.publish raises a
        # plain WebsitePublisherError (wrangler failure/timeout) or
        # CloudflareApiError (deployment verification failure) — all
        # WebsitePublisherError subclasses/instances, all caught here,
        # so this is the one place that needs a log line rather than
        # scattering one at each of those raise sites. `str(exc)` is
        # already a sanitized, human-written message (never a raw
        # subprocess/API response body, never a credential — see each
        # raise site's own message).
        logger.error(
            "Website publish failed for tenant=%s business=%s: %s", tenant_id, business_id, exc
        )
        if website is None:
            website = Website(
                tenant_id=tenant_id,
                business_id=business_id,
                deploy_target=DeployTarget.CLOUDFLARE,
                status=WebsiteStatus.FAILED,
                config=config,
            )
            repo.add(website)
        else:
            website.status = WebsiteStatus.FAILED
            website.config = config
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
    website.config = config

    # One immutable, append-only snapshot per successful publish (P0
    # Phase 20-22) — including a republish a rollback itself performs
    # (app.publishing.versions.rollback_to_version calls publish_website),
    # so version history accumulates through the one publish path rather
    # than a second, parallel bookkeeping mechanism.
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
        site_config=config,
        deploy_url=str(published.url),
        provider_deployment_id=published.deployment_id,
        published_at=website.deployed_at,
        source_website_draft_id=source_website_draft_id,
        artifact_sha256=artifact_sha256,
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


def get_website_state(*, session: Session, tenant_id: UUID, business_id: UUID) -> WebsiteStateResult | None:
    """Read-only, provider-neutral, never touches the hosting provider.
    Returns None (not an error) when this business has never been
    published — a legitimate "still just a preview" state, the same
    convention as the workflow/automation read endpoints."""
    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    if website is None:
        return None
    return _to_state_result(website)
