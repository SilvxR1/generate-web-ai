"""WebsiteDraft lifecycle (Phase 6/7/9/10 of the Creative Orchestrator
continuation): create -> build -> validate -> (preview, read-only) ->
approve -> publish. Reuses app.publishing.build.build_site and
app.publishing.service.publish_website UNCHANGED — this module contains
no parallel deployment system, only the orchestration that requires a
draft to be READY before APPROVED, and APPROVED before PUBLISHED.

Every function here takes an already-open Session and touches no other
Business/Website state than what it's explicitly documented to — a
failure at any step (build, validation persistence) leaves the currently
published Website row (if any) completely untouched, since none of these
functions call publish_website until publish_website_draft, and that only
after the APPROVED check below.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.website_draft import WebsiteDraft
from app.domain.enums import WebsiteDraftStatus
from app.publishing.build import build_site
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsitePublisher
from app.publishing.service import WebsiteStateResult, publish_website
from app.qa.validate import validate_site_config
from app.repositories.website import WebsiteRepository
from app.repositories.website_draft import WebsiteDraftRepository
from app.schemas.site_config import SiteConfigPayload


class WebsiteDraftError(Exception):
    """Raised for every "can't do that to this draft, and here's exactly
    why" case — app.routers.creative maps `code`/`status_code` straight
    onto the HTTP response, mirroring WebsitePublishError's own shape in
    app.publishing.service."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def create_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    site_config: SiteConfigPayload,
    creative_generation_id: UUID | None = None,
) -> WebsiteDraft:
    """Persists `site_config` as a new draft, then runs the real build
    (app.publishing.build.build_site — the same `astro build` subprocess
    publish_website itself uses, see that module's docstring) to prove
    it's actually publishable before anything is shown as a safe preview.
    A build failure is recorded on the draft, never raised — this
    function always returns a WebsiteDraft, whether BUILD_FAILED or
    READY, so the caller (a router) always has something to show/persist.
    The build's own artifact (HTML/CSS bytes) is intentionally discarded —
    see WebsiteDraft's own docstring for why.
    """
    # The generated static site has no other way to learn its own
    # business id — needed client-side for the analytics beacon and the
    # direct (no-n8n) lead-submission fallback to know which business to
    # call (POST /public/businesses/{id}/events, POST .../leads). Set
    # here rather than trusted from Studio's own payload, so it can never
    # be spoofed to point a generated site at a different business.
    site_config.businessId = str(business_id)

    draft = WebsiteDraft(
        tenant_id=tenant_id,
        business_id=business_id,
        creative_generation_id=creative_generation_id,
        site_config=site_config.model_dump(mode="json"),
        status=WebsiteDraftStatus.BUILDING,
    )
    WebsiteDraftRepository(session).add(draft)

    try:
        build_site(site_config)
    except WebsitePublisherError as exc:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = str(exc)
        return draft

    draft.status = WebsiteDraftStatus.READY
    draft.validation_issues = validate_site_config(site_config) or None
    return draft


def approve_website_draft(*, session: Session, tenant_id: UUID, business_id: UUID, draft_id: UUID) -> WebsiteDraft:
    """The explicit human action between preview and publish (Phase 10:
    'GENERATE -> PREVIEW -> APPROVE/APPLY -> PUBLISH'). Only a READY
    draft (built successfully) can be approved — a BUILD_FAILED one is
    hard-blocked, since an unbuildable site can never safely go live no
    matter who approves it. Idempotent on an already-APPROVED draft
    (re-approving is a no-op, not an error) since a human re-confirming
    the same decision shouldn't be treated as a failure."""
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if draft.status is WebsiteDraftStatus.APPROVED:
        return draft
    if draft.status is not WebsiteDraftStatus.READY:
        raise WebsiteDraftError(
            f"Only a READY draft can be approved (current status: {draft.status.value!r}).",
            code="website_draft_not_ready",
            status_code=409,
        )
    draft.status = WebsiteDraftStatus.APPROVED
    draft.approved_at = datetime.now(UTC)
    return draft


def publish_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    publisher: WebsitePublisher,
    n8n_base_url: str | None = None,
) -> WebsiteStateResult:
    """The one call that actually goes live — requires an APPROVED draft
    (Phase 10: generation/build/validation alone never publish). Reuses
    app.publishing.service.publish_website verbatim: same real `astro
    build` + hosting-provider deploy, same lead-capture webhook
    injection, same 'a failed attempt never touches the previously live
    deploy_url' guarantee. If that call fails, WebsitePublishError
    propagates unchanged and this draft is left APPROVED (never silently
    marked PUBLISHED) — the caller can retry the exact same approved
    draft without re-approving.
    """
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if draft.status is not WebsiteDraftStatus.APPROVED:
        raise WebsiteDraftError(
            f"Only an APPROVED draft can be published (current status: {draft.status.value!r}).",
            code="website_draft_not_approved",
            status_code=409,
        )

    site_config = SiteConfigPayload.model_validate(draft.site_config)
    result = publish_website(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        site_config=site_config,
        publisher=publisher,
        n8n_base_url=n8n_base_url,
    )

    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    draft.status = WebsiteDraftStatus.PUBLISHED
    draft.published_at = datetime.now(UTC)
    draft.published_website_id = website.id if website else None
    return result
