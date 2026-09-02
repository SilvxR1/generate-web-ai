"""WorkflowConfig — the execution-engine-neutral contract between
AutomationConfig (business intent, app.domain.business_config) and a
future AutomationEngine. Pure domain data: no n8n, no FastAPI, no
SQLAlchemy, no AI-provider SDKs — same boundary BusinessConfig already
holds itself to (see that package's config.py docstring).

    BusinessConfig.automation  (intent: "we want lead capture + notifications")
        ↓  generator.py
    WorkflowConfig  (a concrete, provider-neutral node graph)
        ↓  (future) n8n translator
    n8n workflow  (out of scope here)
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.domain.business_config import SLUG_PATTERN
from app.domain.workflow_config.connections import WorkflowConnection
from app.domain.workflow_config.nodes import ActionNode, WorkflowNode
from app.domain.workflow_config.triggers import WorkflowTrigger


class ErrorHandlingStrategy(StrEnum):
    STOP = "stop"
    CONTINUE = "continue"
    RETRY = "retry"


class ErrorHandlingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: ErrorHandlingStrategy = ErrorHandlingStrategy.STOP
    max_retries: int = Field(default=0, ge=0, le=10)
    notify_on_failure: bool = False


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    trigger: WorkflowTrigger
    nodes: list[WorkflowNode] = Field(default_factory=list)
    connections: list[WorkflowConnection] = Field(default_factory=list)
    error_handling: ErrorHandlingConfig = Field(default_factory=ErrorHandlingConfig)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def required_capabilities(self) -> list[str]:
        """Always derived from `nodes`, never hand-supplied — there is no
        way for this to drift from what the workflow actually needs."""
        return sorted({node.action.value for node in self.nodes if isinstance(node, ActionNode)})

    @model_validator(mode="after")
    def _unique_node_ids(self) -> "WorkflowConfig":
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ValueError(f"duplicate node id {node.id!r}")
            seen.add(node.id)
        return self

    @model_validator(mode="after")
    def _connections_reference_known_nodes_and_outputs(self) -> "WorkflowConfig":
        nodes_by_id = {node.id: node for node in self.nodes}
        for conn in self.connections:
            if conn.source == "trigger":
                pass
            elif conn.source not in nodes_by_id:
                raise ValueError(f"connection source {conn.source!r} is not 'trigger' or a known node id")
            elif conn.source_output not in nodes_by_id[conn.source].outputs:
                raise ValueError(
                    f"connection source {conn.source!r} has no output {conn.source_output!r} "
                    f"(available: {nodes_by_id[conn.source].outputs})"
                )

            if conn.target == "trigger":
                raise ValueError("connection target cannot be 'trigger'")
            if conn.target not in nodes_by_id:
                raise ValueError(f"connection target {conn.target!r} is not a known node id")
        return self
