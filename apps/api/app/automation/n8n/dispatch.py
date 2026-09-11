"""dispatch_lead_to_workflow — the P2 continuation's canonical-lead-API
fix: n8n becomes strictly downstream of a *persisted* Lead, called
server-side by this backend, never by the browser directly.

Before this module existed, a published site with active automation had
its contact form's `action` rewritten to n8n's webhook URL directly
(app.publishing.service._inject_lead_capture_webhook_url, now removed)
— the browser posted straight to n8n, and n8n's own `lead.store` node
was the *only* thing that ever persisted the Lead. That inverted the
required "lead always persists before automation" guarantee and meant a
generative site (with no SiteConfig to rewrite) had no equivalent path
at all.

Now every site — deterministic or generative — always posts to
POST /public/businesses/{id}/leads (app.routers.public.create_public_lead).
That handler persists the Lead first, then calls
`dispatch_lead_to_workflow` here as one more best-effort step, exactly
like the existing internal-notification/acknowledgement-email steps
already in that function. A dispatch failure (n8n down, network error,
timeout) never raises past this module and never touches the already-
committed Lead row — only `Lead.automation_dispatch_status` records the
outcome, so a human/retry job can tell PENDING/NOT_CONFIGURED apart from
a real FAILED attempt (see app.routers.businesses's
retry_lead_automation_dispatch for the retry path this enables).

The webhook payload includes the already-persisted `lead_id` so
`_internal_callback_node`'s `lead.store` step (app.automation.n8n.translator)
— unaware anything changed, since it still forwards `$json.body` — now
happens to receive that id via the normal request body it already
merges into. app.routers.internal_automation.ingest_lead's own
`lead_id`-aware idempotency (added alongside this module) is what turns
that into a no-op re-confirmation instead of a duplicate insert — no
n8n workflow JSON changes were needed for this to work.
"""

import httpx

from app.automation.n8n.webhook import lead_submitted_webhook_url
from app.db.models.lead import Lead
from app.db.models.workflow import Workflow

_DISPATCH_TIMEOUT_SECONDS = 10.0


class LeadDispatchError(Exception):
    """The webhook call itself failed (network error, non-2xx, timeout)
    — always caught by the caller; this type exists so a caller that
    *does* want to distinguish "didn't try" from "tried and failed" can
    catch it specifically."""


def dispatch_lead_to_workflow(
    *, lead: Lead, workflow: Workflow, n8n_base_url: str, http_client: httpx.Client | None = None
) -> None:
    """Raises LeadDispatchError on any failure — never returns a status
    the caller has to remember to check. The caller
    (app.routers.public.create_public_lead,
    app.routers.businesses.retry_lead_automation_dispatch) is always the
    one deciding what a failure means for `Lead.automation_dispatch_status`,
    this function only ever attempts the one HTTP call."""
    url = lead_submitted_webhook_url(n8n_base_url, workflow.local_workflow_id)
    payload = {
        "lead_id": str(lead.id),
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "message": lead.message,
        "subject": lead.subject,
        "source": lead.source,
        "source_url": lead.source_url,
        "consent": lead.consent_given,
    }
    client = http_client or httpx.Client(timeout=_DISPATCH_TIMEOUT_SECONDS)
    try:
        response = client.post(url, json=payload)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LeadDispatchError(f"n8n webhook dispatch failed: {exc}") from exc
    finally:
        if http_client is None:
            client.close()
