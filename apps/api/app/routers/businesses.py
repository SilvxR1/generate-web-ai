from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.analysis.analyzer import BusinessAnalysisResult, BusinessAnalyzer
from app.analysis.errors import AnalyzerProviderError, InvalidAnalysisOutputError
from app.automation.activation import (
    AutomationActivationError,
    AutomationStateResult,
    activate_lead_capture_automation,
    deactivate_lead_capture_automation,
    get_automation_state,
)
from app.automation.n8n import N8nClient
from app.config import settings
from app.db.models.business import Business
from app.db.models.lead import Lead
from app.db.models.workflow import Workflow
from app.dependencies import (
    get_business_analyzer,
    get_current_tenant_id,
    get_n8n_client,
    get_optional_n8n_client,
    get_session,
    get_website_publisher,
)
from app.domain.business_config import BusinessConfig, Location
from app.domain.enums import BusinessVertical, WorkflowStatus
from app.domain.workflow_config import WorkflowConfig, generate_lead_capture_workflow, recommended_automation_template
from app.errors import AppError
from app.publishing.publisher import WebsitePublisher
from app.publishing.service import (
    WebsitePublishError,
    WebsiteStateResult,
    get_website_state,
    publish_website,
)
from app.repositories.lead import LeadRepository
from app.repositories.website import WebsiteRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.business import (
    AutomationRecommendationResponse,
    BusinessAutomationSummary,
    BusinessRead,
    BusinessSummary,
    BusinessWebsiteSummary,
    BusinessWriteRequest,
)
from app.schemas.business_analysis import BusinessAnalysisRequest
from app.schemas.lead import LeadRead, LeadStatusUpdateRequest
from app.schemas.site_config import SiteConfigPayload
from app.services.business_service import BusinessNotFoundError, BusinessService, SlugConflictError

router = APIRouter(prefix="/businesses", tags=["businesses"])

# A separate router, deliberately NOT nested under /businesses. This
# endpoint used to live at GET /businesses/summary, which FastAPI
# matched to GET /businesses/{business_id} instead (business_id="summary"
# fails UUID parsing -> 422) regardless of which route was declared
# first in this file: a literal segment competing with a path parameter
# at the same position isn't resolved by declaration order the way two
# literal paths are. Giving this endpoint its own, structurally disjoint
# prefix removes the collision entirely instead of relying on route
# ordering to avoid it. See list_businesses_summary below.
business_summaries_router = APIRouter(prefix="/business-summaries", tags=["businesses"])


def _not_found() -> AppError:
    return AppError("Business not found.", code="business_not_found", status_code=status.HTTP_404_NOT_FOUND)


def _slug_conflict(exc: SlugConflictError) -> AppError:
    return AppError(str(exc), code="slug_conflict", status_code=status.HTTP_409_CONFLICT)


def _load_business_config(session: Session, tenant_id: UUID, business_id: UUID) -> BusinessConfig | None:
    try:
        business = BusinessService(session).get(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc
    if business.config is None:
        return None
    return BusinessConfig.model_validate(business.config)


@router.post("", response_model=BusinessRead, status_code=status.HTTP_201_CREATED)
def create_business(
    payload: BusinessWriteRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> Business:
    try:
        return BusinessService(session).create(tenant_id, payload)
    except SlugConflictError as exc:
        raise _slug_conflict(exc) from exc


@router.post("/analyze", response_model=BusinessAnalysisResult)
def analyze_business(
    payload: BusinessAnalysisRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    analyzer: BusinessAnalyzer = Depends(get_business_analyzer),
) -> BusinessAnalysisResult:
    """Proposes a BusinessConfig from a natural-language briefing —
    never persists it. The caller (Studio) is expected to show a human
    the proposal, `missing_information`, and `questions`, and only a
    separate, human-reviewed POST /businesses call actually creates the
    Business. `tenant_id` authenticates the caller (see
    get_current_tenant_id's docstring); this route reads no tenant data
    and writes nothing.
    """
    del tenant_id
    try:
        return analyzer.analyze(payload.briefing)
    except InvalidAnalysisOutputError as exc:
        raise AppError(str(exc), code="invalid_analysis_output", status_code=status.HTTP_502_BAD_GATEWAY) from exc
    except AnalyzerProviderError as exc:
        raise AppError(str(exc), code="analyzer_provider_error", status_code=status.HTTP_502_BAD_GATEWAY) from exc


@router.get("", response_model=list[BusinessRead])
def list_businesses(
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[Business]:
    return BusinessService(session).list(tenant_id)


@router.get("/automation-recommendation", response_model=AutomationRecommendationResponse)
def get_automation_recommendation(
    vertical: BusinessVertical,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> AutomationRecommendationResponse:
    """Studio's minimal window into
    app.domain.workflow_config.vertical_templates: given a vertical,
    the recommended automation for it — nothing tenant- or
    business-specific, so this reads no tenant data and writes nothing
    (`tenant_id` is only for the same caller-authentication reasoning
    every other route in this router uses, see
    get_current_tenant_id's own docstring). Declared *before*
    GET /{business_id} below so "automation-recommendation" is never
    swallowed by that route's {business_id} path parameter — same
    literal-before-parameterized ordering POST /analyze already
    relies on.

    A pure, stateless lookup: recompute-on-every-call, never persisted,
    never a competing source of truth for a business's actual
    BusinessConfig.automation. Studio only ever writes this into its
    own local draft when a user explicitly applies it — this endpoint
    itself changes nothing.
    """
    del tenant_id
    template = recommended_automation_template(vertical)
    return AutomationRecommendationResponse(
        lead_notifications=template.lead_notifications,
        customer_acknowledgement=template.customer_acknowledgement,
        follow_up_enabled=template.follow_up_enabled,
        follow_up_delay_hours=template.follow_up_delay_hours,
    )


@business_summaries_router.get("", response_model=list[BusinessSummary])
def list_businesses_summary(
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[BusinessSummary]:
    """Studio's dashboard listing: every business this tenant owns, plus
    a lightweight snapshot of each one's *persisted* website/automation
    state — the same source of truth GET .../website and GET
    .../automation each read for a single business, batch-loaded here
    (one query for every business's Website row, one for every
    business's Workflow row) so opening the dashboard never fires an
    N+1 request per business.

    Lives on its own /business-summaries prefix (business_summaries_router
    above) rather than /businesses/summary — see that router's own
    comment for why nesting this under /businesses collided with GET
    /businesses/{business_id}.

    Deliberately excludes `config` (the full BusinessConfig) — see
    BusinessSummary's own docstring for why.
    """
    businesses = BusinessService(session).list(tenant_id)
    business_ids = [business.id for business in businesses]

    websites_by_business = {
        website.business_id: website
        for website in WebsiteRepository(session).list_for_businesses(tenant_id, business_ids)
    }
    workflows_by_business: dict[UUID, Workflow] = {}
    for candidate_workflow in WorkflowRepository(session).list_for_businesses(tenant_id, business_ids):
        workflows_by_business.setdefault(candidate_workflow.business_id, candidate_workflow)

    summaries: list[BusinessSummary] = []
    for business in businesses:
        location = None
        if business.config:
            location_data = business.config.get("business_profile", {}).get("location")
            if location_data:
                location = Location.model_validate(location_data)

        website = websites_by_business.get(business.id)
        workflow = workflows_by_business.get(business.id)

        summaries.append(
            BusinessSummary(
                id=business.id,
                name=business.name,
                slug=business.slug,
                vertical=business.vertical,
                status=business.status,
                location=location,
                created_at=business.created_at,
                updated_at=business.updated_at,
                website=BusinessWebsiteSummary(status=website.status, live_url=website.deploy_url)
                if website is not None
                else None,
                automation=(
                    BusinessAutomationSummary(status=workflow.status, active=workflow.status == WorkflowStatus.ACTIVE)
                    if workflow is not None
                    else None
                ),
            )
        )
    return summaries


@router.get("/{business_id}", response_model=BusinessRead)
def get_business(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> Business:
    try:
        return BusinessService(session).get(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc


@router.put("/{business_id}", response_model=BusinessRead)
def update_business(
    business_id: UUID,
    payload: BusinessWriteRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> Business:
    try:
        return BusinessService(session).update(tenant_id, business_id, payload)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc
    except SlugConflictError as exc:
        raise _slug_conflict(exc) from exc


@router.get("/{business_id}/workflow-preview", response_model=WorkflowConfig | None)
def preview_business_workflow(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> WorkflowConfig | None:
    """Read-only preview of the WorkflowConfig `generate_lead_capture_workflow`
    would produce from this business's *stored* config — the exact same
    generator a future AutomationEngine would consume, never re-implemented
    here. Never runs anything, never touches n8n, never creates a
    Workflow/WorkflowVersion row (Section: "NO activar workflows todavía").

    Returns null (200, not an error) when the business has no config yet
    or hasn't enabled lead-capture automation — that's a legitimate
    "nothing to preview yet" state, distinct from a real failure.
    """
    config = _load_business_config(session, tenant_id, business_id)
    if config is None or not config.automation.lead_capture:
        return None

    return generate_lead_capture_workflow(config)


@router.get("/{business_id}/website", response_model=WebsiteStateResult | None)
def get_business_website(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> WebsiteStateResult | None:
    """Provider-neutral read of this business's *persisted* deployment
    state (app.db.models.website.Website) — never touches the hosting
    provider. Returns null (200, not an error) when this business has
    never been published, the same "nothing to show yet" convention as
    GET .../workflow-preview and .../automation.
    """
    _ensure_business_exists(session, tenant_id, business_id)
    return get_website_state(session=session, tenant_id=tenant_id, business_id=business_id)


@router.get("/{business_id}/leads", response_model=list[LeadRead])
def list_business_leads(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[Lead]:
    """Every lead captured for this business so far (via the
    lead.submitted -> n8n -> /internal/leads loop), most recent first.
    Tenant- and business-scoped through LeadRepository, same as every
    other tenant-scoped read in this router — a tenant can never see
    another tenant's leads, even for a business id they happen to know.
    """
    _ensure_business_exists(session, tenant_id, business_id)
    return LeadRepository(session).list_for_business(tenant_id, business_id)


@router.patch("/{business_id}/leads/{lead_id}/status", response_model=LeadRead)
def update_lead_status(
    business_id: UUID,
    lead_id: UUID,
    payload: LeadStatusUpdateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> Lead:
    """Moves a lead along NEW -> CONTACTED -> WON/LOST. The only field
    this endpoint can change (LeadStatusUpdateRequest forbids any other
    field); no transition rules are enforced beyond "a valid LeadStatus"
    — Studio's LeadsList is free to move a lead to any of the four
    states directly, same as clicking a dropdown.

    Scoped through LeadRepository.get_for_business (tenant_id AND
    business_id AND lead_id all required to match) rather than the base
    repository's tenant-only `get`, so a lead can be updated only via
    its own business's route — not another business the same tenant
    owns, and never another tenant's business at all.
    """
    _ensure_business_exists(session, tenant_id, business_id)
    lead = LeadRepository(session).get_for_business(tenant_id, business_id, lead_id)
    if lead is None:
        raise AppError("Lead not found.", code="lead_not_found", status_code=status.HTTP_404_NOT_FOUND)
    lead.status = payload.status
    session.flush()
    return lead


@router.post("/{business_id}/website/publish", response_model=WebsiteStateResult)
def publish_business_website(
    business_id: UUID,
    payload: SiteConfigPayload,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    publisher: WebsitePublisher = Depends(get_website_publisher),
) -> WebsiteStateResult:
    """The one human-triggered action that turns a website *preview*
    into a real, live static site — never called automatically after
    analysis or business creation. `payload` is the exact SiteConfig
    Studio's own preview already computed via `generateSiteConfig()`
    (see app.schemas.site_config's docstring for why this backend never
    recomputes it) — this route never accepts a bare BusinessConfig.
    Returns a provider-neutral result — never the hosting provider's own
    deployment payload, never a credential.

    If a lead-capture contact form is present and this business already
    has an *active* automation, its real n8n webhook URL is wired into
    the form before publishing (see
    app.publishing.service._inject_lead_capture_webhook_url) — never a
    fabricated one; missing N8N_BASE_URL or no active automation just
    leaves the form without an `action`, exactly as it is today.
    """
    _ensure_business_exists(session, tenant_id, business_id)

    try:
        return publish_website(
            session=session,
            tenant_id=tenant_id,
            business_id=business_id,
            site_config=payload,
            publisher=publisher,
            n8n_base_url=settings.n8n_base_url,
        )
    except WebsitePublishError as exc:
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc


def _ensure_business_exists(session: Session, tenant_id: UUID, business_id: UUID) -> None:
    try:
        BusinessService(session).get(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc


@router.get("/{business_id}/automation", response_model=AutomationStateResult | None)
def get_business_automation(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> AutomationStateResult | None:
    """Provider-neutral read of this business's *persisted* automation
    state (app.db.models.workflow.Workflow) — never touches n8n, never a
    source of temporary/React-only state. Returns null (200, not an
    error) when automation has never been activated for this business,
    the same "nothing to show yet" convention as GET .../workflow-preview.
    """
    _ensure_business_exists(session, tenant_id, business_id)
    return get_automation_state(session=session, tenant_id=tenant_id, business_id=business_id)


@router.post("/{business_id}/automation/activate", response_model=AutomationStateResult)
def activate_business_automation(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    n8n_client: N8nClient = Depends(get_n8n_client),
) -> AutomationStateResult:
    """The one human-triggered action that turns a workflow *preview*
    into a real, active n8n workflow — never called automatically after
    analysis or business creation. Loads the persisted BusinessConfig,
    regenerates the exact same WorkflowConfig the preview endpoint
    showed, validates it can actually be activated (capabilities the
    engine supports, required n8n configuration present), then creates
    (or reactivates) it via AutomationEngine and persists the result.
    Reasonably idempotent — see activate_lead_capture_automation's
    docstring. Returns a provider-neutral result — never n8n's own
    workflow JSON, never a credential.
    """
    config = _load_business_config(session, tenant_id, business_id)
    if config is None:
        raise AppError(
            "This business has no configuration to activate automation from.",
            code="no_business_config",
            status_code=status.HTTP_409_CONFLICT,
        )

    try:
        return activate_lead_capture_automation(
            session=session,
            business_config=config,
            tenant_id=tenant_id,
            business_id=business_id,
            settings=settings,
            client=n8n_client,
        )
    except AutomationActivationError as exc:
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc


@router.post("/{business_id}/automation/deactivate", response_model=AutomationStateResult)
def deactivate_business_automation(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    n8n_client: N8nClient = Depends(get_n8n_client),
) -> AutomationStateResult:
    """The counterpart to .../automation/activate: flips a persisted,
    active automation back to inactive on the remote engine. Never
    deletes the remote n8n workflow — its persisted status changes only
    once the remote deactivate call actually succeeds (see
    deactivate_lead_capture_automation's docstring).
    """
    _ensure_business_exists(session, tenant_id, business_id)

    try:
        return deactivate_lead_capture_automation(
            session=session,
            tenant_id=tenant_id,
            business_id=business_id,
            settings=settings,
            client=n8n_client,
        )
    except AutomationActivationError as exc:
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    n8n_client: N8nClient | None = Depends(get_optional_n8n_client),
) -> None:
    """Deletes a business and every row that hangs off it. Business's
    own docstring (app.db.models.business) documents the six
    `cascade="all, delete-orphan"` relationships — website, workflows,
    integrations (and, through those, their credentials), executions,
    leads, internal_notifications — that SQLAlchemy removes on its own
    once the Business row itself is deleted; nothing here has to do
    that cleanup by hand.

    The one thing cascade delete can't do: an *active* remote n8n
    workflow keeps running even after its local Workflow row
    disappears, since n8n has no idea the business behind it was ever
    deleted. So if this business's persisted automation is currently
    ACTIVE, this deactivates it on the remote engine first — the same
    deactivate_lead_capture_automation the dedicated deactivate route
    uses — turning it off rather than deleting the remote n8n workflow
    object itself, because N8nClient/N8nAutomationEngine
    (app.automation.n8n) expose create/update/activate/deactivate but
    no `delete_workflow`; actually removing the remote object is
    deferred cleanup until that capability exists. A business with no
    automation, or automation that was never activated, deletes fine on
    a server that has never configured n8n at all (n8n is fetched via
    get_optional_n8n_client, not the hard-requiring get_n8n_client) —
    but if this business *does* have an active automation and n8n isn't
    configured, or the deactivate call itself fails, the whole delete
    fails (never leaving an active remote automation behind with no
    local record of it anymore) and nothing is deleted.

    Cloudflare Pages deployment/project cleanup is likewise deferred:
    CloudflarePagesClient/CloudflarePagesPublisher
    (app.publishing.cloudflare) expose only publish + get_status, no
    delete/unpublish method, so there's no safe existing abstraction to
    call here. The Website row (deploy_url, provider_deployment_id) is
    still removed from this database by the cascade above; the actual
    Cloudflare Pages deployment, if this business was ever published,
    is left running until a delete/unpublish capability is added.
    """
    workflow_row = WorkflowRepository(session).get_for_business(tenant_id, business_id)
    if workflow_row is not None and workflow_row.status == WorkflowStatus.ACTIVE and workflow_row.n8n_workflow_id:
        if n8n_client is None:
            raise AppError(
                "This business has an active automation and n8n is not configured on this server — "
                "deactivate it manually, or configure n8n, before deleting this business.",
                code="n8n_not_configured",
                status_code=503,
            )
        try:
            deactivate_lead_capture_automation(
                session=session,
                tenant_id=tenant_id,
                business_id=business_id,
                settings=settings,
                client=n8n_client,
            )
        except AutomationActivationError as exc:
            raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc

    try:
        BusinessService(session).delete(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc
