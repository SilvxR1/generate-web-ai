from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.business_config import SLUG_PATTERN
from app.domain.workflow_config.actions import ActionInputs, ActionType


class ConditionOperator(StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    EXISTS = "exists"


class NodeCondition(BaseModel):
    """`field` is a dotted path into the triggering event's payload
    (e.g. "lead.email") — resolved by the future AutomationEngine, not
    interpreted here."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    operator: ConditionOperator
    value: str | float | bool | None = None

    @model_validator(mode="after")
    def _value_matches_operator(self) -> "NodeCondition":
        needs_value = self.operator in (ConditionOperator.EQUALS, ConditionOperator.CONTAINS)
        if needs_value and self.value is None:
            raise ValueError(f"operator {self.operator!r} requires a value")
        if self.operator is ConditionOperator.EXISTS and self.value is not None:
            raise ValueError("operator 'exists' does not take a value")
        return self


class ActionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    type: Literal["action"] = "action"
    action: ActionType
    inputs: ActionInputs
    outputs: list[str] = Field(default_factory=lambda: ["done"], min_length=1)

    @model_validator(mode="after")
    def _inputs_match_action(self) -> "ActionNode":
        if self.inputs.action != self.action:
            raise ValueError(
                f"node {self.id!r}: inputs are configured for action {self.inputs.action!r}, "
                f"but node.action is {self.action!r}"
            )
        return self


class ConditionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    type: Literal["condition"] = "condition"
    condition: NodeCondition
    outputs: list[str] = Field(default_factory=lambda: ["true", "false"], min_length=1)


WorkflowNode = Annotated[ActionNode | ConditionNode, Field(discriminator="type")]
