from datetime import datetime
from typing import Any

from app.automation.engine import AutomationEngine, ExecutionRecord, RemoteWorkflow
from app.automation.n8n.client import N8nClient
from app.automation.n8n.translator import N8nTranslationContext, translate_workflow
from app.config import Settings
from app.domain.enums import ExecutionStatus
from app.domain.workflow_config import WorkflowConfig

_N8N_STATUS_MAP: dict[str, ExecutionStatus] = {
    "success": ExecutionStatus.SUCCESS,
    "error": ExecutionStatus.FAILED,
    "crashed": ExecutionStatus.FAILED,
    "canceled": ExecutionStatus.FAILED,
    "running": ExecutionStatus.RUNNING,
    "waiting": ExecutionStatus.PENDING,
    "new": ExecutionStatus.PENDING,
}


def translation_context_from_settings(
    settings: Settings, *, tenant_id: str | None = None, business_id: str | None = None
) -> N8nTranslationContext:
    """`tenant_id`/`business_id` scope the resulting context to one
    business's workflow — pass them when translating a real business's
    WorkflowConfig so lead.store/notification.send calls carry
    ownership; omit them (e.g. for a translation that doesn't need the
    callback endpoints, or in tests) to get the original,
    unenriched-body behavior."""
    base = settings.internal_api_base_url.rstrip("/")
    return N8nTranslationContext(
        internal_leads_url=f"{base}/internal/leads",
        internal_notifications_url=f"{base}/internal/notifications",
        email_credential_id=settings.n8n_email_credential_id,
        tenant_id=tenant_id,
        business_id=business_id,
        internal_automation_credential_id=settings.n8n_internal_automation_credential_id,
    )


class N8nAutomationEngine(AutomationEngine):
    """The first, replaceable AutomationEngine implementation. Nothing
    outside this module (and translator.py/client.py) knows n8n
    exists — callers depend on AutomationEngine."""

    def __init__(self, client: N8nClient, context: N8nTranslationContext) -> None:
        self._client = client
        self._context = context

    def create_workflow(self, workflow: WorkflowConfig) -> RemoteWorkflow:
        payload = translate_workflow(workflow, self._context)
        return _to_remote_workflow(self._client.create_workflow(payload))

    def update_workflow(self, remote_id: str, workflow: WorkflowConfig) -> RemoteWorkflow:
        payload = translate_workflow(workflow, self._context)
        return _to_remote_workflow(self._client.update_workflow(remote_id, payload))

    def activate_workflow(self, remote_id: str) -> RemoteWorkflow:
        return _to_remote_workflow(self._client.activate_workflow(remote_id))

    def deactivate_workflow(self, remote_id: str) -> RemoteWorkflow:
        return _to_remote_workflow(self._client.deactivate_workflow(remote_id))

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        return _to_execution_record(self._client.get_execution(execution_id))

    def list_executions(self, remote_workflow_id: str) -> list[ExecutionRecord]:
        data = self._client.list_executions(remote_workflow_id)
        return [_to_execution_record(item) for item in data.get("data", [])]


def _to_remote_workflow(data: dict[str, Any]) -> RemoteWorkflow:
    return RemoteWorkflow(remote_id=str(data["id"]), name=data.get("name", ""), active=bool(data.get("active", False)))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_execution_record(data: dict[str, Any]) -> ExecutionRecord:
    raw_status = data.get("status") or ("success" if data.get("finished") else "running")
    status = _N8N_STATUS_MAP.get(raw_status, ExecutionStatus.FAILED)

    error_summary: str | None = None
    if status is ExecutionStatus.FAILED:
        error = ((data.get("data") or {}).get("resultData") or {}).get("error") or {}
        error_summary = error.get("message") or raw_status

    return ExecutionRecord(
        remote_id=str(data["id"]),
        workflow_remote_id=str(data.get("workflowId", "")),
        status=status,
        started_at=_parse_datetime(data.get("startedAt")),
        finished_at=_parse_datetime(data.get("stoppedAt")),
        error_summary=error_summary,
    )
