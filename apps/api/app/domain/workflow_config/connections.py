from pydantic import BaseModel, ConfigDict, Field


class WorkflowConnection(BaseModel):
    """One edge in the workflow's node graph. `source` is either the
    literal string "trigger" (the workflow's single entry point) or a
    node id; `source_output` names which of that node's declared
    `outputs` this edge follows (a `condition` node has "true"/"false";
    most `action` nodes just have "done"). Referential integrity
    (source/target actually exist, source_output actually exists on that
    node) is enforced at the WorkflowConfig level, where the full node
    list is known — see workflow.py.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=100)
    source_output: str = Field(default="done", min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=100)
