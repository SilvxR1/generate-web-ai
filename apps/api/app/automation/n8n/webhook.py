"""The one place that knows the URL shape of a lead-capture workflow's
n8n webhook. Used by app.automation.n8n.translator (to build the
workflow's own trigger node when creating it in n8n) and by
app.publishing.service (to wire that same URL into a published site's
contact form) — never duplicated inline in either place.
"""


def lead_submitted_webhook_path(workflow_id: str) -> str:
    """n8n webhook path for a `lead.submitted`-triggered workflow,
    namespaced by `workflow_id` (app.domain.workflow_config.generator's
    `f"{slug}-lead-capture"` convention) so every business's lead-capture
    automation gets its own webhook. This function doesn't care what
    produced `workflow_id`, only how to turn one into a path."""
    return f"lead-submitted/{workflow_id}"


def lead_submitted_webhook_url(n8n_base_url: str, workflow_id: str) -> str:
    """n8n's convention for an *activated* workflow's webhook:
    `{instance}/webhook/{path}` — as opposed to `/webhook-test/{path}`,
    which only exists while a workflow is being edited/tested live in
    the n8n editor. Only meaningful once the workflow has actually been
    activated; callers are responsible for checking that first (see
    app.publishing.service._inject_lead_capture_webhook_url)."""
    return f"{n8n_base_url.rstrip('/')}/webhook/{lead_submitted_webhook_path(workflow_id)}"
