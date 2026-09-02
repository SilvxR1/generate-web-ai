"""AutomationConfig — business-level intent/capabilities, NOT an
executable workflow.

`automation.follow_up.enabled = true` means the business WANTS
automatic follow-up; it does not mean a Workflow/WorkflowVersion
(app.db.models.workflow) exists yet, let alone an n8n workflow. Turning
this intent into a real, executable workflow is
app.domain.workflow_config.generator.generate_lead_capture_workflow's
job — see FollowUpConfig.delay_hours below for the one field that
generator actually consumes.
"""

from pydantic import BaseModel, ConfigDict, Field


class FollowUpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # Free-form duration string (e.g. "2d", "4h") — human-facing only,
    # never parsed. Kept for backward compatibility with configs that
    # already set it; superseded by `delay_hours` below for anything
    # that needs an actual number.
    delay: str | None = Field(default=None, max_length=20)
    # The one number generate_lead_capture_workflow needs to build a
    # WAIT node (app.domain.workflow_config.actions.WaitInputs) — a
    # simple `follow_up_delay_hours`-shaped option, deliberately not the
    # free-form `delay` string above (parsing "2d"/"4h" would be its own
    # bit of logic this MVP doesn't need). Defaults to a day so enabling
    # follow-up without also setting this still produces a sane workflow.
    delay_hours: int = Field(default=24, gt=0, le=720)


class AutomationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_capture: bool = False
    lead_notifications: bool = False
    customer_acknowledgement: bool = False
    follow_up: FollowUpConfig = Field(default_factory=FollowUpConfig)
    # Forward-compatible escape hatch for capability flags that don't
    # warrant a dedicated field (and therefore a schema_version bump)
    # yet.
    enabled_features: list[str] = Field(default_factory=list)
