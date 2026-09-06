"""Business intent (BusinessConfig.automation) -> a real, active n8n
workflow, with its activation state persisted in
app.db.models.workflow.Workflow — so a business's automation survives a
restart and can be deactivated/reactivated without losing track of which
remote workflow backs it. Every step the brief asks for lives here, in
order: load happens at the router (see app.routers.businesses), then
generate -> validate -> build context -> create/reactivate/deactivate ->
persist -> return, a provider-neutral result with no n8n JSON and no
credential ever in it.
"""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.automation.errors import AutomationEngineError
from app.automation.n8n import N8nAutomationEngine, N8nClient, translation_context_from_settings
from app.config import Settings
from app.db.models.workflow import Workflow
from app.domain.business_config import BusinessConfig
from app.domain.enums import WorkflowStatus
from app.domain.workflow_config import ActionType, WorkflowConfig, generate_lead_capture_workflow
from app.repositories.workflow import WorkflowRepository

_SUPPORTED_CAPABILITIES = {action.value for action in ActionType}


class AutomationActivationError(Exception):
    """Raised for every "can't activate/deactivate, and here's exactly
    why" case — missing intent, an unsupported capability, missing n8n
    configuration, nothing persisted yet to deactivate, or the n8n call
    itself failing. app.routers.businesses maps `code`/`status_code`
    straight onto the HTTP response; never a bare 500."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AutomationStateResult(BaseModel):
    """Provider-neutral snapshot of a business's *persisted* automation
    state (app.db.models.workflow.Workflow) — no n8n workflow JSON, no
    node payloads, no credential of any kind. What activate, deactivate,
    and the read-only GET endpoint all return, so a caller (Studio) can
    treat this — not its own component state — as the source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    remote_id: str | None
    name: str
    status: WorkflowStatus
    active: bool
    version: int
    required_capabilities: list[str]
    activated_at: datetime | None
    updated_at: datetime | None


def _to_state_result(workflow: Workflow) -> AutomationStateResult:
    return AutomationStateResult(
        workflow_id=workflow.local_workflow_id,
        remote_id=workflow.n8n_workflow_id,
        name=workflow.name,
        status=workflow.status,
        active=workflow.status == WorkflowStatus.ACTIVE,
        version=workflow.version,
        required_capabilities=list(workflow.required_capabilities),
        activated_at=workflow.activated_at,
        updated_at=workflow.updated_at,
    )


def _validate_activatable(workflow: WorkflowConfig) -> None:
    # email.send used to also need an n8n SMTP credential check here;
    # it now translates to a callback into our own backend instead (see
    # app.automation.n8n.translator), the same "not configured yet is a
    # send-time no-op, not an activation-time hard failure" shape
    # lead.follow_up_email/notification.send already had — so no
    # per-capability configuration check is needed here anymore.
    unsupported = sorted(set(workflow.required_capabilities) - _SUPPORTED_CAPABILITIES)
    if unsupported:
        raise AutomationActivationError(
            f"This workflow needs capabilities the automation engine doesn't support yet: {', '.join(unsupported)}.",
            code="unsupported_capability",
            status_code=422,
        )


def activate_lead_capture_automation(
    *,
    session: Session,
    business_config: BusinessConfig,
    tenant_id: UUID,
    business_id: UUID,
    settings: Settings,
    client: N8nClient,
) -> AutomationStateResult:
    """`client` is already-validated-as-configured (see
    app.dependencies.get_n8n_client) and injected rather than built here,
    so tests can pass one wired to a mocked transport without needing a
    real n8n instance.

    Reasonably idempotent:
    * no persisted Workflow yet -> create + activate remotely, persist.
    * persisted but not active -> push the current definition and
      reactivate remotely (in case the business's config changed since
      it was first created), then persist.
    * already active -> return the persisted state as-is; n8n is never
      called again, so a repeated request can never create a duplicate.

    Every remote call happens *before* any local row is created or
    mutated, so a failure at any point (see the `except` below) leaves
    whatever was already persisted completely unchanged.
    """
    if not business_config.automation.lead_capture:
        raise AutomationActivationError(
            "Lead-capture automation is not enabled for this business — enable it in the business's "
            "configuration before activating.",
            code="automation_not_enabled",
            status_code=409,
        )

    workflow_config = generate_lead_capture_workflow(business_config)
    _validate_activatable(workflow_config)

    repo = WorkflowRepository(session)
    existing = repo.get_for_business(tenant_id, business_id)

    if existing is not None and existing.status == WorkflowStatus.ACTIVE:
        return _to_state_result(existing)

    context = translation_context_from_settings(settings, tenant_id=str(tenant_id), business_id=str(business_id))
    engine = N8nAutomationEngine(client, context)

    try:
        if existing is not None and existing.n8n_workflow_id:
            remote = engine.update_workflow(existing.n8n_workflow_id, workflow_config)
            remote = engine.activate_workflow(remote.remote_id)
        else:
            remote = engine.create_workflow(workflow_config)
            remote = engine.activate_workflow(remote.remote_id)
    except AutomationEngineError as exc:
        raise AutomationActivationError(
            f"Activating this automation failed: {exc}",
            code="automation_activation_failed",
            status_code=502,
        ) from exc

    now = datetime.now(UTC)
    if existing is not None:
        existing.name = remote.name
        existing.status = WorkflowStatus.ACTIVE
        existing.n8n_workflow_id = remote.remote_id
        existing.local_workflow_id = workflow_config.id
        existing.version = workflow_config.version
        existing.required_capabilities = list(workflow_config.required_capabilities)
        existing.activated_at = now
        workflow_row = existing
    else:
        workflow_row = repo.add(
            Workflow(
                tenant_id=tenant_id,
                business_id=business_id,
                name=remote.name,
                status=WorkflowStatus.ACTIVE,
                n8n_workflow_id=remote.remote_id,
                local_workflow_id=workflow_config.id,
                version=workflow_config.version,
                required_capabilities=list(workflow_config.required_capabilities),
                activated_at=now,
            )
        )

    return _to_state_result(workflow_row)


def deactivate_lead_capture_automation(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    settings: Settings,
    client: N8nClient,
) -> AutomationStateResult:
    """Loads the persisted Workflow, calls AutomationEngine.deactivate_workflow
    on its remote id, and updates local state *only if that remote call
    succeeds* — a failure leaves the persisted row exactly as it was.
    Never deletes the remote n8n workflow, only flips it inactive.
    Already-inactive is a no-op returning the current state (n8n isn't
    called again), the same idempotency shape as activation above.
    """
    workflow_row = WorkflowRepository(session).get_for_business(tenant_id, business_id)
    if workflow_row is None or not workflow_row.n8n_workflow_id:
        raise AutomationActivationError(
            "No automation has been activated for this business yet — nothing to deactivate.",
            code="automation_not_activated",
            status_code=404,
        )

    if workflow_row.status != WorkflowStatus.ACTIVE:
        return _to_state_result(workflow_row)

    context = translation_context_from_settings(settings, tenant_id=str(tenant_id), business_id=str(business_id))
    engine = N8nAutomationEngine(client, context)

    try:
        remote = engine.deactivate_workflow(workflow_row.n8n_workflow_id)
    except AutomationEngineError as exc:
        raise AutomationActivationError(
            f"Deactivating this automation failed: {exc}",
            code="automation_deactivation_failed",
            status_code=502,
        ) from exc

    workflow_row.status = WorkflowStatus.INACTIVE
    workflow_row.name = remote.name
    return _to_state_result(workflow_row)


def get_automation_state(*, session: Session, tenant_id: UUID, business_id: UUID) -> AutomationStateResult | None:
    """Read-only, provider-neutral, never touches n8n. Returns None (not
    an error) when nothing has ever been activated for this business —
    a legitimate "nothing to show" state, same convention as the
    workflow-preview endpoint."""
    workflow_row = WorkflowRepository(session).get_for_business(tenant_id, business_id)
    if workflow_row is None:
        return None
    return _to_state_result(workflow_row)
