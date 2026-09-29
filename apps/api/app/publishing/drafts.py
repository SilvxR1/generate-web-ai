"""WebsiteDraft lifecycle (Phase 6/7/9/10 of the Creative Orchestrator
continuation): create -> build -> validate -> (preview, read-only) ->
approve -> publish. This module contains no parallel deployment system,
only the orchestration that requires a draft to be READY before
APPROVED, and APPROVED before PUBLISHED.

A8.3.4.1 — BUILD ONCE / PROMOTE. A draft is built exactly once:

    SiteConfig (or generative source) -> build -> PlatformContract
    -> canonical SHA-256 -> immutable archive (StorageProvider)
    -> artifact_key + artifact_sha256 persisted -> READY
    -> APPROVED -> load archive -> re-verify SHA-256 -> deploy those bytes

Publish never calls build_site (nor the generative rebuild): it deploys
the stored artifact through app.publishing.service.publish_prebuilt_artifact
— the same WebsitePublisher and Website/WebsiteVersion bookkeeping as
every other publish. Consistency choices:

- A draft only becomes READY after its archive is saved; a storage
  failure leaves it BUILD_FAILED (never publishable). The archive is
  written before the request's DB transaction commits, so a later commit
  failure can only leave an *unreferenced* private archive behind
  (harmless; no API ever lists or serves it) — never a READY row
  pointing at nothing.
- A missing, unreadable, corrupt or hash-mismatched archive refuses
  publication before the hosting provider is called: no deployment, no
  WebsiteVersion, the live site untouched. Nothing is ever rebuilt or
  "repaired".
- Legacy drafts (no artifact, created before A8.3.4.1) are refused with
  an owner-facing "create a new proposal" message — silently rebuilding
  them would break the invariant.
- PlatformContract is NOT re-run at publish: the creation-time result is
  authoritative, and the verified hash proves the deployed bytes are
  exactly the ones that passed it. Re-running against the *current*
  BusinessConfig could only ever disagree about a different question
  (has the business changed since?), and no contract implementation is
  ever allowed to mutate a stored artifact either way.

Every function here takes an already-open Session and touches no other
Business/Website state than what it's explicitly documented to — a
failure at any step (build, validation, artifact storage/verification)
leaves the currently published Website row (if any) completely untouched,
since nothing here deploys until publish_*website_draft, and that only
after the APPROVED check and a successful artifact integrity check.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.creative.director_orchestrator import domain_from_row
from app.creative.errors import CreativeProviderError
from app.creative.frontend_engine.browser_qa import BrowserQAUnavailableError
from app.creative.frontend_engine.build import inline_script_hashes, rebuild_from_archive
from app.creative.frontend_engine.engine import FrontendEngineer
from app.creative.frontend_engine.sandboxed_browser_qa import MAX_OFFLINE_ASSET_BYTES
from app.creative.frontend_engine.visual_qa import run_visual_qa
from app.creative.observability import log_pipeline_stage
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.website_draft import WebsiteDraft
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import BusinessTruth, derive_business_truth
from app.domain.creative import CreativeBriefAsset
from app.domain.creative.image_qa import direction_is_approval_eligible
from app.domain.enums import GenerationEngine, WebsiteDraftStatus
from app.publishing.artifact_store import (
    ArtifactError,
    ArtifactUnavailableError,
    load_draft_artifact,
    store_draft_artifact,
)
from app.publishing.build import build_site
from app.publishing.cloudflare.engine import preview_branch_for
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import PreviewPublisher, WebsiteArtifact, WebsitePublisher
from app.publishing.security_headers import generate_headers_file
from app.publishing.service import WebsiteStateResult, publish_prebuilt_artifact
from app.qa.platform_contract import PLATFORM_CONTRACT_VERSION, validate_platform_contract
from app.qa.truth_contract import TruthContractResult, validate_truth_contract
from app.qa.validate import validate_site_config
from app.repositories.business_asset import BusinessAssetRepository
from app.repositories.creative_direction import CreativeDirectionRepository
from app.repositories.generative_website_artifact import GenerativeWebsiteArtifactRepository
from app.repositories.website import WebsiteRepository
from app.repositories.website_draft import WebsiteDraftRepository
from app.schemas.site_config import SiteConfigPayload
from app.storage import StorageProvider
from app.storage.errors import StorageProviderError
from app.storage.private import PrivateArtifactStorage

logger = logging.getLogger(__name__)

_ARTIFACT_STORE_FAILED_MESSAGE = (
    "The validated website could not be saved, so this proposal can't be published. "
    "Please try creating it again."
)
_LEGACY_DRAFT_MESSAGE = (
    "This proposal was created before validated websites were stored, so it can't be published as-is. "
    "Please create a new proposal and publish that one. Your current website is unchanged."
)
_ARTIFACT_UNAVAILABLE_MESSAGE = (
    "This proposal's validated website could not be loaded, so nothing was published. "
    "Your current website is unchanged. Please try again; if it keeps failing, create a new proposal."
)
_ARTIFACT_UNVERIFIED_MESSAGE = (
    "This proposal's validated website failed its integrity check, so nothing was published. "
    "Your current website is unchanged. Please create a new proposal."
)


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


def _promote_with_stored_artifact(
    *, draft: WebsiteDraft, artifact_storage: PrivateArtifactStorage, artifact: WebsiteArtifact, issues: list[str]
) -> None:
    """The last step of every successful draft creation (either engine):
    persist the exact artifact that just passed PlatformContract, and
    only then mark the draft READY. Any storage failure leaves the draft
    BUILD_FAILED — never a READY draft without an artifact behind it."""
    draft.validation_issues = issues or None
    try:
        stored = store_draft_artifact(
            artifact_storage,
            tenant_id=draft.tenant_id,
            business_id=draft.business_id,
            draft_id=draft.id,
            artifact=artifact,
        )
    except (ArtifactError, StorageProviderError, OSError, ValueError) as exc:
        logger.error(
            "website_artifact_store_failed draft=%s business=%s error=%s: %s",
            draft.id,
            draft.business_id,
            type(exc).__name__,
            exc,
        )
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = _ARTIFACT_STORE_FAILED_MESSAGE
        return
    draft.artifact_key = stored.storage_key
    draft.artifact_sha256 = stored.sha256
    draft.status = WebsiteDraftStatus.READY


def _log_truth_contract(result: TruthContractResult, *, draft: WebsiteDraft, mode: str) -> None:
    """Safe metadata only — rule ids and counts, never content or truth."""
    logger.info(
        "truth_contract draft=%s business=%s version=%s mode=%s passed=%s blocking=%d advisory=%d rules=%s",
        draft.id,
        draft.business_id,
        result.version,
        mode,
        result.passed,
        len(result.violations),
        len(result.warnings),
        ",".join(sorted({f.rule for f in result.findings})) or "-",
    )


def _load_verified_artifact(draft: WebsiteDraft, artifact_storage: PrivateArtifactStorage) -> WebsiteArtifact:
    """The only way a draft's artifact reaches a publisher (or, in
    A8.3.4.2, a preview): the stored archive, integrity-verified against
    the hash recorded at creation. Never rebuilds."""
    if draft.artifact_key is None or draft.artifact_sha256 is None:
        logger.warning("website_artifact_missing draft=%s business=%s reason=legacy_draft", draft.id, draft.business_id)
        raise WebsiteDraftError(_LEGACY_DRAFT_MESSAGE, code="website_draft_artifact_missing", status_code=409)
    try:
        return load_draft_artifact(
            artifact_storage, storage_key=draft.artifact_key, expected_sha256=draft.artifact_sha256, draft_id=draft.id
        )
    except ArtifactUnavailableError as exc:
        raise WebsiteDraftError(
            _ARTIFACT_UNAVAILABLE_MESSAGE, code="website_draft_artifact_unavailable", status_code=503
        ) from exc
    except ArtifactError as exc:
        raise WebsiteDraftError(
            _ARTIFACT_UNVERIFIED_MESSAGE, code="website_draft_artifact_integrity_failed", status_code=409
        ) from exc


def _require_approved(
    session: Session, tenant_id: UUID, business_id: UUID, draft_id: UUID, *, generative: bool = False
) -> WebsiteDraft:
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if generative and draft.engine is not GenerationEngine.GENERATIVE:
        raise GenerativeDraftError(
            "This draft was not produced by the generative engine.", code="not_a_generative_draft", status_code=409
        )
    if draft.status is not WebsiteDraftStatus.APPROVED:
        raise WebsiteDraftError(
            f"Only an APPROVED draft can be published (current status: {draft.status.value!r}).",
            code="website_draft_not_approved",
            status_code=409,
        )
    return draft


def _mark_published(
    session: Session, draft: WebsiteDraft, preview_publisher: PreviewPublisher | None = None
) -> None:
    website = WebsiteRepository(session).get_by_business(draft.tenant_id, draft.business_id)
    draft.status = WebsiteDraftStatus.PUBLISHED
    draft.published_at = datetime.now(UTC)
    draft.published_website_id = website.id if website else None
    _retire_preview_best_effort(draft, preview_publisher)


# --- A8.3.4.2a: real draft preview ---------------------------------------------

PREVIEW_TTL = timedelta(days=7)
_PREVIEWABLE = (WebsiteDraftStatus.READY, WebsiteDraftStatus.APPROVED)


@dataclass(frozen=True)
class DraftPreview:
    preview_url: str
    created_at: datetime
    expires_at: datetime


def _aware(value: datetime) -> datetime:
    # SQLite doesn't round-trip tzinfo (see publish_website's own note);
    # every value this module writes is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _current_preview(draft: WebsiteDraft, now: datetime) -> DraftPreview | None:
    if not (draft.preview_url and draft.preview_deployment_id and draft.preview_created_at):
        return None
    created = _aware(draft.preview_created_at)
    if now >= created + PREVIEW_TTL:
        return None
    return DraftPreview(preview_url=draft.preview_url, created_at=created, expires_at=created + PREVIEW_TTL)


def ensure_draft_preview(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    artifact_storage: PrivateArtifactStorage,
    preview_publisher: PreviewPublisher,
    now: datetime | None = None,
) -> DraftPreview:
    """Lazily deploys (or reuses) the real preview of a READY/APPROVED
    draft: the EXACT stored artifact, loaded from private storage and
    SHA-256-verified — never build_site, never a transformed copy. A live
    preview younger than PREVIEW_TTL is returned as-is; an expired one is
    redeployed from the same artifact. Never changes the draft's approval
    state and never touches production. The row lock serializes
    concurrent clicks for the same draft."""
    now = now or datetime.now(UTC)
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id, for_update=True)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if draft.status not in _PREVIEWABLE:
        raise WebsiteDraftError(
            "This proposal can't be previewed"
            + (" — it's already live." if draft.status is WebsiteDraftStatus.PUBLISHED else ".")
            + f" (current status: {draft.status.value!r})",
            code="website_draft_not_previewable",
            status_code=409,
        )

    existing = _current_preview(draft, now)
    if existing is not None:
        return existing

    artifact = _load_verified_artifact(draft, artifact_storage)
    branch = preview_branch_for(draft.id)
    try:
        deployed = preview_publisher.publish_preview(branch=branch, artifact=artifact)
    except WebsitePublisherError as exc:
        logger.error("website_preview_failed draft=%s business=%s error=%s", draft.id, business_id, exc)
        raise WebsiteDraftError(
            "The preview couldn't be prepared right now. Your live website is unchanged; please try again.",
            code="website_draft_preview_failed",
            status_code=502,
        ) from exc

    superseded = draft.preview_deployment_id
    draft.preview_deployment_id = deployed.deployment_id
    draft.preview_url = str(deployed.url)
    draft.preview_created_at = now
    logger.info("website_preview_deployed draft=%s business=%s", draft.id, business_id)
    if superseded and superseded != deployed.deployment_id:
        _delete_superseded_best_effort(preview_publisher, superseded, draft.id)
    return DraftPreview(preview_url=draft.preview_url, created_at=now, expires_at=now + PREVIEW_TTL)


def _delete_superseded_best_effort(preview_publisher: PreviewPublisher, deployment_id: str, draft_id: UUID) -> None:
    delete = getattr(preview_publisher, "delete_superseded", None)
    if delete is None:
        return
    try:
        delete(deployment_id)
    except Exception as exc:  # noqa: BLE001 — cleanup must never fail the preview
        logger.warning("website_preview_cleanup_failed draft=%s error=%s", draft_id, type(exc).__name__)


def _retire_preview_best_effort(draft: WebsiteDraft, preview_publisher: PreviewPublisher | None) -> None:
    """After a successful production publish: the preview has done its
    job. Best-effort — a retirement failure never fails the publish that
    already succeeded; the preview metadata is cleared either way so it's
    never handed out again."""
    deployment_id = draft.preview_deployment_id
    draft.preview_deployment_id = None
    draft.preview_url = None
    draft.preview_created_at = None
    if not deployment_id or preview_publisher is None:
        return
    try:
        preview_publisher.retire_preview(branch=preview_branch_for(draft.id), deployment_id=deployment_id)
        logger.info("website_preview_retired draft=%s", draft.id)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("website_preview_retire_failed draft=%s error=%s", draft.id, type(exc).__name__)


def create_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    site_config: SiteConfigPayload,
    artifact_storage: PrivateArtifactStorage,
    creative_generation_id: UUID | None = None,
    business_config: BusinessConfig | None = None,
    business_truth: BusinessTruth | None = None,
) -> WebsiteDraft:
    """Persists `site_config` as a new draft, then runs the real build
    (app.publishing.build.build_site — the same `astro build` subprocess
    publish_website itself uses, see that module's docstring) to prove
    it's actually publishable before anything is shown as a safe preview.
    A build failure is recorded on the draft, never raised — this
    function always returns a WebsiteDraft, whether BUILD_FAILED or
    READY, so the caller (a router) always has something to show/persist.
    A8.3.4.1: this is the draft's ONE build — the artifact that passes is
    archived through `artifact_storage` (PRIVATE, A8.3.4.1b) and becomes exactly what Publish deploys
    (see this module's docstring); READY is only reached once it's saved.

    P2: when `business_config` is provided (the real call path — see
    app.routers.creative.create_website_draft_route), the same build's
    file output is also scanned by
    app.qa.platform_contract.validate_platform_contract *before* being
    stored — the identical, engine-agnostic contract GENERATIVE drafts
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

    # v0.2 R3: BASIC/legacy output is truth-checked in ADVISORY mode —
    # findings are recorded on the draft, never block it (the legacy
    # generator can still fall back to a generated logo asset; see docs,
    # R3). Generative drafts are blocked instead.
    if business_truth is not None:
        truth_result = validate_truth_contract(artifact.files, business_truth=business_truth)
        _log_truth_contract(truth_result, draft=draft, mode="advisory")
        issues += [f"[TruthContract advisory:{f.rule}] {f.description}" for f in truth_result.findings]

    _promote_with_stored_artifact(draft=draft, artifact_storage=artifact_storage, artifact=artifact, issues=issues)
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
    artifact_storage: PrivateArtifactStorage,
    preview_publisher: PreviewPublisher | None = None,
) -> WebsiteStateResult:
    """The one call that actually goes live — requires an APPROVED draft
    (Phase 10: generation/build/validation alone never publish). A8.3.4.1:
    deploys the draft's stored, integrity-verified artifact — the exact
    bytes built and validated at creation — and never calls build_site.
    Same 'a failed attempt never touches the previously live deploy_url'
    guarantee as every other publish (publish_prebuilt_artifact). If
    anything fails, the error propagates and this draft is left APPROVED
    (never silently marked PUBLISHED) — the caller can retry the exact
    same approved draft without re-approving.
    """
    draft = _require_approved(session, tenant_id, business_id, draft_id)
    artifact = _load_verified_artifact(draft, artifact_storage)
    assert draft.artifact_sha256 is not None and draft.artifact_key is not None  # by _load_verified_artifact
    result = publish_prebuilt_artifact(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        artifact=artifact,
        config=dict(draft.site_config or {}),
        publisher=publisher,
        source_website_draft_id=draft.id,
        artifact_sha256=draft.artifact_sha256,
        artifact_key=draft.artifact_key,
    )
    _mark_published(session, draft, preview_publisher)
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
    artifact_storage: PrivateArtifactStorage,
    assets: Sequence[CreativeBriefAsset] = (),
    api_base_url: str | None = None,
    business_truth: BusinessTruth | None = None,
) -> WebsiteDraft:
    """The GENERATIVE counterpart to create_website_draft above — same
    DRAFT -> BUILDING -> READY|BUILD_FAILED state machine
    (WebsiteDraftStatus), same PlatformContract gate, just reached via
    the AI Frontend Engineer instead of packages/website-generator.
    Never falls back to the deterministic engine on failure (P2.14): a
    FrontendEngineer/build/PlatformContract failure here always produces
    a BUILD_FAILED draft or a raised GenerativeDraftError, never a
    silently-substituted deterministic result.

    Deliberately does NOT run real-browser Visual QA inline (that's a
    real Chromium launch, seconds long): see run_visual_qa_for_draft
    below, a separate, explicitly-triggered step a READY draft moves
    through next (Studio's own QA_RUNNING stage), kept off this
    synchronous creation path so every other generative-draft test in
    this codebase doesn't need a real browser and Chromium isn't a
    dependency of the hot request path.
    """
    direction_row = CreativeDirectionRepository(session).get_for_business(tenant_id, business_id, creative_direction_id)
    if direction_row is None:
        raise GenerativeDraftError(
            "Creative direction not found.", code="creative_direction_not_found", status_code=404
        )
    # P2.7: a candidate whose generated image failed a BLOCKING Visual QA check
    # cannot be turned into a website. Only a RECORDED blocking failure refuses:
    # older directions and internal-fallback directions (no QA record), and
    # candidates whose QA merely could not run, are unaffected.
    if not direction_is_approval_eligible(direction_row.generation_metadata):
        raise GenerativeDraftError(
            "This creative direction's generated image failed a blocking Visual QA check, "
            "so it cannot be used to build a website. Generate new directions instead.",
            code="visual_qa_blocked",
            status_code=409,
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
            business_truth=business_truth,
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

    # v0.2 R3: TruthContract — the generated output may transform
    # presentation but never expand BusinessTruth. A blocking violation
    # means BUILD_FAILED: the artifact is never stored, never READY, never
    # approvable. Deterministic; no provider is called again to "fix" it.
    truth = business_truth or derive_business_truth(business_config=business_config, assets=assets)
    truth_result = validate_truth_contract(result.artifact.files, business_truth=truth)
    _log_truth_contract(truth_result, draft=draft, mode="blocking")
    issues += [f"[TruthContract:{f.rule}] {f.description}" for f in truth_result.findings]
    if not truth_result.passed:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = "TruthContract violation(s): " + truth_result.summary()
        draft.validation_issues = issues or None
        return draft

    # A8.3.4.1: the built output (platform config already injected) is
    # what gets stored and later promoted — never rebuilt from source.
    _promote_with_stored_artifact(
        draft=draft, artifact_storage=artifact_storage, artifact=result.artifact, issues=issues
    )
    return draft


def judge_generative_candidate(
    *,
    draft: WebsiteDraft,
    files: dict[str, bytes],
    business_config: BusinessConfig,
    business_truth: BusinessTruth,
    artifact_storage: PrivateArtifactStorage,
    api_base_url: str | None,
) -> str | None:
    """v0.2 R4.1: the trusted verdict on a candidate returned by an isolated
    execution host — the same gates, in the same order and with the same
    messages, as create_generative_website_draft's inline path. Returns
    None when the draft is READY (artifact stored, SHA-256 recorded), else
    the failed gate ("platform_contract" | "truth_contract" | "storage").

    The candidate's own `_headers` (CSP) is discarded and re-derived here
    from its HTML: security headers are never taken from the untrusted host.
    """
    files = {name: data for name, data in files.items() if name != "_headers"}
    html = [data.decode("utf-8", errors="ignore") for name, data in files.items() if name.endswith(".html")]
    files["_headers"] = generate_headers_file(script_hashes=inline_script_hashes(html), public_api_origin=api_base_url)
    artifact = WebsiteArtifact(files=files, entry_point="index.html")

    contract_result = validate_platform_contract(artifact.files, business_config=business_config)
    issues = [f"[PlatformContract:{f.rule}] {f.message}" for f in contract_result.findings]
    if not contract_result.passed:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = "PlatformContract violation(s): " + "; ".join(
            f.message for f in contract_result.blocking_violations
        )
        draft.validation_issues = issues or None
        return "platform_contract"

    truth_result = validate_truth_contract(artifact.files, business_truth=business_truth)
    _log_truth_contract(truth_result, draft=draft, mode="blocking")
    issues += [f"[TruthContract:{f.rule}] {f.description}" for f in truth_result.findings]
    if not truth_result.passed:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = "TruthContract violation(s): " + truth_result.summary()
        draft.validation_issues = issues or None
        return "truth_contract"

    _promote_with_stored_artifact(draft=draft, artifact_storage=artifact_storage, artifact=artifact, issues=issues)
    return None if draft.status is WebsiteDraftStatus.READY else "storage"


def _visual_qa_assets(
    session: Session, tenant_id: UUID, business_id: UUID, storage: StorageProvider
) -> dict[str, bytes]:
    """v0.2 R4.1: sandboxed Visual QA has no network, so the business's own
    stored assets are handed in as bytes, keyed by the exact URL generated
    pages embed (CreativeBriefAsset.url == BusinessAsset.storage_url).
    Best effort per asset: one that can't be loaded simply shows up as a
    broken image finding, never as a silent pass."""
    assets: dict[str, bytes] = {}
    total = 0
    for asset in BusinessAssetRepository(session).list_for_business(tenant_id, business_id):
        if asset.storage_key is None or asset.unavailable_reason is not None:
            continue
        try:
            content = storage.load(asset.storage_key)
        except Exception:  # noqa: BLE001 — surfaced as a broken-image finding instead
            logger.warning("visual QA asset could not be loaded (asset_id=%s)", asset.id)
            continue
        total += len(content)
        if total > MAX_OFFLINE_ASSET_BYTES:
            break
        assets[asset.storage_url] = content
    return assets


def run_visual_qa_for_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    storage: StorageProvider,
    artifact_storage: PrivateArtifactStorage,
    api_base_url: str | None = None,
) -> GenerativeWebsiteArtifact:
    """P2 continuation Part 4 (Visual QA V1) — Studio's own QA_RUNNING
    step: rebuilds a READY generative draft's already-archived source
    (same `rebuild_from_archive` pattern publish_generative_website_draft
    uses — never re-invokes the LLM) and runs a real headless-browser
    pass (app.creative.frontend_engine.visual_qa) against the real
    output, persisting screenshots and findings on the draft's
    GenerativeWebsiteArtifact row. Kept separate from
    create_generative_website_draft so draft creation itself never needs
    a real browser. Does not change the draft's own status — a Visual QA
    failure is surfaced for a human to review (see `visual_qa_state` on
    the returned row), never silently turned into BUILD_FAILED or a
    deterministic substitution."""
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise WebsiteDraftError("Website draft not found.", code="website_draft_not_found", status_code=404)
    if draft.engine is not GenerationEngine.GENERATIVE:
        raise GenerativeDraftError(
            "This draft was not produced by the generative engine.", code="not_a_generative_draft", status_code=409
        )
    if draft.status not in (WebsiteDraftStatus.READY, WebsiteDraftStatus.APPROVED):
        raise WebsiteDraftError(
            f"Visual QA requires a READY or APPROVED draft (current status: {draft.status.value!r}).",
            code="website_draft_not_ready",
            status_code=409,
        )

    artifact_row = GenerativeWebsiteArtifactRepository(session).get_for_draft(tenant_id, business_id, draft_id)
    if artifact_row is None:
        raise GenerativeDraftError(
            "This draft has no generative artifact record.", code="generative_artifact_missing", status_code=500
        )

    if draft.artifact_key is not None:
        # A8.3.4.1: QA the exact artifact Publish will deploy.
        artifact = _load_verified_artifact(draft, artifact_storage)
    else:
        # Legacy draft (pre-A8.3.4.1): no stored build output, only source.
        # Publish refuses these anyway; QA still inspects a rebuild.
        archive = storage.load(artifact_row.workspace_key)
        artifact = rebuild_from_archive(archive, business_id=str(business_id), api_base_url=api_base_url)
    try:
        visual_result = run_visual_qa(
            artifact.files,
            business_id=str(business_id),
            storage=storage,
            offline_assets=_visual_qa_assets(session, tenant_id, business_id, storage),
        )
    except BrowserQAUnavailableError as exc:
        # Never a silent skip/pass (P2.14's "no deterministic
        # substitution" rule extends here): the caller gets an explicit,
        # actionable 503 instead of the request hanging or a fabricated
        # visual_qa_state. See BrowserQAUnavailableError's own docstring
        # for why this can only be a runtime/environment problem
        # (missing Playwright/Chromium), never a QA *finding*.
        raise GenerativeDraftError(str(exc), code="visual_qa_unavailable", status_code=503) from exc

    artifact_row.visual_qa_state = {
        "passed": visual_result.passed,
        "findings": [
            {"viewport": f.viewport, "check": f.check, "passed": f.passed, "detail": f.detail}
            for f in visual_result.browser_qa.findings
        ],
    }
    artifact_row.screenshot_keys = visual_result.screenshot_keys
    return artifact_row


def publish_generative_website_draft(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    publisher: WebsitePublisher,
    artifact_storage: PrivateArtifactStorage,
    preview_publisher: PreviewPublisher | None = None,
) -> WebsiteStateResult:
    """The GENERATIVE counterpart to publish_website_draft above — same
    APPROVED requirement, same A8.3.4.1 promotion of the stored,
    integrity-verified build output (never re-invokes the LLM, never
    re-runs npm/astro). Website/WebsiteVersion `config` stores a small
    generative marker (never a fabricated SiteConfig) since there is no
    SiteConfig for a generative build."""
    draft = _require_approved(session, tenant_id, business_id, draft_id, generative=True)

    artifact_row = GenerativeWebsiteArtifactRepository(session).get_for_draft(tenant_id, business_id, draft_id)
    if artifact_row is None:
        raise GenerativeDraftError(
            "This draft has no generative artifact record.", code="generative_artifact_missing", status_code=500
        )

    artifact = _load_verified_artifact(draft, artifact_storage)
    assert draft.artifact_sha256 is not None and draft.artifact_key is not None  # by _load_verified_artifact
    direction_id = artifact_row.creative_direction_id
    config_snapshot = {
        "engine": "generative",
        "creative_direction_id": str(direction_id) if direction_id else None,
        "generator_provider": artifact_row.generator_provider,
        "generator_model": artifact_row.generator_model,
        "workspace_key": artifact_row.workspace_key,
    }
    result = publish_prebuilt_artifact(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        artifact=artifact,
        config=config_snapshot,
        publisher=publisher,
        source_website_draft_id=draft.id,
        artifact_sha256=draft.artifact_sha256,
        artifact_key=draft.artifact_key,
    )
    _mark_published(session, draft, preview_publisher)
    return result
