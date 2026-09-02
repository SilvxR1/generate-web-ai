"""AutomationEngine — the execution-engine-neutral interface between a
WorkflowConfig (app.domain.workflow_config, pure domain data) and
whatever actually runs it. N8nAutomationEngine (app.automation.n8n) is
the first, replaceable implementation — nothing outside app.automation.n8n
should need to know n8n exists.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ExecutionStatus
from app.domain.workflow_config import WorkflowConfig


class RemoteWorkflow(BaseModel):
    """A workflow as it exists on the execution engine — provider-neutral
    (no n8n-specific fields)."""

    model_config = ConfigDict(extra="forbid")

    remote_id: str
    name: str
    active: bool


class ExecutionRecord(BaseModel):
    """One run of a remote workflow — provider-neutral. Reuses
    ExecutionStatus (app.domain.enums), the same vocabulary
    app.db.models.execution.Execution already persists runs under."""

    model_config = ConfigDict(extra="forbid")

    remote_id: str
    workflow_remote_id: str
    status: ExecutionStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: str | None = None


class AutomationEngine(ABC):
    @abstractmethod
    def create_workflow(self, workflow: WorkflowConfig) -> RemoteWorkflow: ...

    @abstractmethod
    def update_workflow(self, remote_id: str, workflow: WorkflowConfig) -> RemoteWorkflow: ...

    @abstractmethod
    def activate_workflow(self, remote_id: str) -> RemoteWorkflow: ...

    @abstractmethod
    def deactivate_workflow(self, remote_id: str) -> RemoteWorkflow: ...

    @abstractmethod
    def get_execution(self, execution_id: str) -> ExecutionRecord: ...

    @abstractmethod
    def list_executions(self, remote_workflow_id: str) -> list[ExecutionRecord]: ...
