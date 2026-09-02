"""What starts a workflow. A closed catalog, like everything else in this
package — no arbitrary trigger source, no code."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class TriggerType(StrEnum):
    LEAD_SUBMITTED = "lead.submitted"
    WEBHOOK = "webhook"


class LeadSubmittedTrigger(BaseModel):
    """Fires on the website's `lead.submitted` DOM event (see
    packages/blocks/Contact.astro) — no config needed, it's an internal,
    already-neutral signal."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[TriggerType.LEAD_SUBMITTED] = TriggerType.LEAD_SUBMITTED


class WebhookTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[TriggerType.WEBHOOK] = TriggerType.WEBHOOK
    path: str = Field(min_length=1, max_length=200)
    method: Literal["GET", "POST"] = "POST"


WorkflowTrigger = Annotated[LeadSubmittedTrigger | WebhookTrigger, Field(discriminator="type")]
