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

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.creative.director_orchestrator import domain_from_row
from app.creative.errors import CreativeProviderError
from app.creative.frontend_engine.engine import FrontendEngineer
from app.creative.observability import log_pipeline_stage
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.website_draft import WebsiteDraft
from app.domain.business_config import BusinessConfig
from app.domain.creative import CreativeBriefAsset
from app.domain.enums import GenerationEngine, WebsiteDraftStatus
from app.publishing.build import build_site
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsitePublisher
from app.publishing.service import WebsiteStateResult, publish_generative_website, publish_website
from app.qa.platform_contract import PLATFORM_CONTRACT_VERSION, validate_platform_contract
from app.qa.validate import validate_site_config
from app.repositories.creative_direction import CreativeDirectionRepository
from app.repositories.generative_website_artifact import GenerativeWebsiteArtifactRepository
from app.repositories.website import WebsiteRepository
from app.repositories.website_draft import WebsiteDraftRepository
from app.schemas.site_config import SiteConfigPayload
from app.storage import StorageProvider


class GenerativeDraftError(Exception):
    """Raised for every "can't create/publish this generative draft, and
    here's exactly why" case — mirrors WebsiteDraftError's own shape.
    Never caught and silently turned into a deterministic fallback
    (P2.14): a router lets this propagate as a real failure."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


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
    business_config: BusinessConfig | None = None,
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

    P2: when `business_config` is provided (the real call path — see
    app.routers.creative.create_website_draft_route), the same build's
    transient file output is also scanned by
    app.qa.platform_contract.validate_platform_contract *before* being
    discarded — the identical, engine-agnostic contract GENERATIVE drafts
    are held to (app.creative.frontend_engine). A BLOCKING violation
    (P2.8: a dead CTA, a disconnected lead form, ...) demotes this draft
    to BUILD_FAILED exactly like a real build failure — never READY, so
    it can never reach APPROVED. `business_config` stays optional (not
    required) only so existing callers/tests that predate P2 keep working
    unchanged; every real router call path passes it.
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
        artifact = build_site(site_config)
    except WebsitePublisherError as exc:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = str(exc)
        return draft

    issues = list(validate_site_config(site_config))
    if business_config is not None:
        contract_result = validate_platform_contract(artifact.files, business_config=business_config)
        issues += [f"[PlatformContract:{f.rule}] {f.message}" for f in contract_result.findings]
        if not contract_result.passed:
            draft.status = WebsiteDraftStatus.BUILD_FAILED
            draft.build_error = (
                "PlatformContract violation(s): " + "; ".join(f.message for f in contract_result.blocking_violations)
            )
            draft.validation_issues = issues or None
            return draft

    draft.status = WebsiteDraftStatus.READY
    draft.validation_issues = issues or None
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


# --- Generative engine (P2 continuation): the same lifecycle, a
# --- different "how READY was reached" path -----------------------------


def create_generative_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    business_config: BusinessConfig,
    creative_direction_id: UUID,
    frontend_engineer: FrontendEngineer,
    assets: Sequence[CreativeBriefAsset] = (),
    api_base_url: str | None = None,
) -> WebsiteDraft:
    """The GENERATIVE counterpart to create_website_draft above — same
    DRAFT -> BUILDING -> READY|BUILD_FAILED state machine
    (WebsiteDraftStatus), same PlatformContract gate, just reached via
    the AI Frontend Engineer instead of packages/website-generator.
    Never falls back to the deterministic engine on failure (P2.14): a
    FrontendEngineer/build/PlatformContract failure here always produces
    a BUILD_FAILED draft or a raised GenerativeDraftError, never a
    silently-substituted deterministic result.
    """
    direction_row = CreativeDirectionRepository(session).get_for_business(tenant_id, business_id, creative_direction_id)
    if direction_row is None:
        raise GenerativeDraftError(
            "Creative direction not found.", code="creative_direction_not_found", status_code=404
        )
    creative_direction = domain_from_row(direction_row)

    draft = WebsiteDraft(
        tenant_id=tenant_id,
        business_id=business_id,
        creative_generation_id=direction_row.creative_generation_id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.BUILDING,
    )
    WebsiteDraftRepository(session).add(draft)

    try:
        result = frontend_engineer.generate(
            business_config=business_config,
            creative_direction=creative_direction,
            assets=assets,
            platform_contract_version=PLATFORM_CONTRACT_VERSION,
            business_id=str(business_id),
            api_base_url=api_base_url,
        )
    except CreativeProviderError as exc:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = str(exc)
        return draft

    contract_result = validate_platform_contract(result.artifact.files, business_config=business_config)
    log_pipeline_stage(
        stage="platform_contract",
        business_id=business_id,
        provider=result.generator_provider,
        result="success" if contract_result.passed else "failure",
        blocking_violation_count=len(contract_result.blocking_violations),
    )
    issues = [f"[PlatformContract:{f.rule}] {f.message}" for f in contract_result.findings]

    artifact_row = GenerativeWebsiteArtifact(
        tenant_id=tenant_id,
        business_id=business_id,
        website_draft_id=draft.id,
        creative_direction_id=creative_direction_id,
        framework=result.framework,
        workspace_key=result.workspace_key,
        build_command=result.build_command,
        output_dir=result.output_dir,
        dependencies=result.dependencies,
        platform_contract_version=PLATFORM_CONTRACT_VERSION,
        qa_state=contract_result.model_dump(mode="json"),
        generator_provider=result.generator_provider,
        generator_model=result.generator_model,
        generated_at=datetime.now(UTC),
        duration_ms=result.duration_ms,
    )
    GenerativeWebsiteArtifactRepository(session).add(artifact_row)

    if not contract_result.passed:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = "PlatformContract violation(s): " + "; ".join(
            f.message for f in contract_result.blocking_violations
        )
        draft.validation_issues = issues or None
        return draft

    draft.status = WebsiteDraftStatus.READY
    draft.validation_issues = issues or None
    return draft


def publish_generative_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    publisher: WebsitePublisher,
    storage: StorageProvider,
    api_base_url: str | None = None,
) -> WebsiteStateResult:
    """The GENERATIVE counterpart to publish_website_draft above —
    requires an APPROVED draft, rebuilds from the durably-archived
    generative source (never re-invokes the LLM — see
    app.creative.frontend_engine.build.rebuild_from_archive's own
    docstring for why), and reuses
    app.publishing.service.publish_generative_website, which itself
    reuses the same WebsitePublisher.publish/Website/WebsiteVersion
    persistence the deterministic path already uses."""
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if draft.engine is not GenerationEngine.GENERATIVE:
        raise GenerativeDraftError(
            "This draft was not produced by the generative engine.", code="not_a_generative_draft", status_code=409
        )
    if draft.status is not WebsiteDraftStatus.APPROVED:
        raise WebsiteDraftError(
            f"Only an APPROVED draft can be published (current status: {draft.status.value!r}).",
            code="website_draft_not_approved",
            status_code=409,
        )

    artifact_row = GenerativeWebsiteArtifactRepository(session).get_for_draft(tenant_id, business_id, draft_id)
    if artifact_row is None:
        raise GenerativeDraftError(
            "This draft has no generative artifact record.", code="generative_artifact_missing", status_code=500
        )

    result = publish_generative_website(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        artifact_row=artifact_row,
        publisher=publisher,
        storage=storage,
        api_base_url=api_base_url,
    )

    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    draft.status = WebsiteDraftStatus.PUBLISHED
    draft.published_at = datetime.now(UTC)
    draft.published_website_id = website.id if website else None
    return result
