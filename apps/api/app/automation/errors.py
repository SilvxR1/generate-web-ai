class AutomationEngineError(Exception):
    """Base for every error an AutomationEngine implementation raises —
    the type a caller depending on AutomationEngine (not on any specific
    adapter) should catch."""


class UnsupportedNodeError(AutomationEngineError):
    """A WorkflowConfig node has no translation to the target engine yet
    (e.g. a condition node, not supported by the n8n translator in this
    phase). Raised instead of silently dropping the node."""


class UnsupportedActionError(AutomationEngineError):
    """A node's action is in WorkflowConfig's closed catalog but can't
    actually be translated right now — typically missing configuration
    (e.g. no N8N_EMAIL_CREDENTIAL_ID for an email.send node). Raised
    instead of emitting a workflow that would silently fail at
    execution time."""
