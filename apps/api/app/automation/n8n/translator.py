"""WorkflowConfig -> n8n workflow JSON. Pure function, no HTTP, no
n8n API calls — app.automation.n8n.engine is what actually talks to
n8n. WorkflowConfig itself is never touched or reshaped to look like an
n8n workflow (see app.domain.workflow_config) — this module is the only
place that knows n8n's node-type vocabulary.

Mapping (see each _translate_* function's docstring for why):
  trigger  lead.submitted / webhook  -> n8n-nodes-base.webhook
  action   http.request              -> n8n-nodes-base.httpRequest   (direct)
  action   lead.store                -> n8n-nodes-base.httpRequest   (-> our own backend)
  action   lead.lookup               -> n8n-nodes-base.httpRequest   (-> our own backend, GET)
  action   lead.follow_up_email      -> n8n-nodes-base.httpRequest   (-> our own backend)
  action   notification.send         -> n8n-nodes-base.httpRequest   (-> our own backend)
  action   email.send                -> n8n-nodes-base.emailSend     (credential by reference, fromEmail from settings.smtp_from_address, to/subject/text resolved from _EMAIL_RECIPIENT_FIELD/_EMAIL_TEMPLATES)
  action   wait                      -> n8n-nodes-base.wait
  node     condition                 -> n8n-nodes-base.if

No code/shell node is ever produced — every mapping above is a native
n8n node type; there is no fallback that shells out to a Function/Code
node for anything this translator can't otherwise express.

Every node the workflow contains is checked before any translation
happens, so a workflow with one unsupported node fails outright rather
than emitting a partial/broken n8n workflow.
"""

import json
from dataclasses import dataclass
from typing import Any

from app.automation.errors import UnsupportedActionError, UnsupportedNodeError
from app.automation.n8n.webhook import lead_submitted_webhook_path
from app.domain.workflow_config import (
    ActionNode,
    ActionType,
    ConditionNode,
    ConditionOperator,
    EmailRecipient,
    EmailSendInputs,
    HttpRequestInputs,
    LeadSubmittedTrigger,
    WaitInputs,
    WebhookTrigger,
    WorkflowConfig,
    WorkflowNode,
)
from app.security.ssrf import SSRFValidationError, validate_outbound_url

_CONDITION_OPERATION: dict[ConditionOperator, str] = {
    ConditionOperator.EQUALS: "equals",
    ConditionOperator.CONTAINS: "contains",
    ConditionOperator.EXISTS: "exists",
}

# email.send's `to` is a role (EmailRecipient), never a literal address —
# this is what actually resolves that role against the *real* field name
# on the input item. EMAIL_SEND always sits directly downstream of
# store-lead (see generator.generate_lead_capture_workflow), whose
# translated httpRequest node returns our own /internal/leads response
# (LeadResponse) verbatim as $json — not the raw webhook body, and not
# wrapped in `.body` — so "customer" resolves to the LeadResponse field
# `email`, never a field literally named "customer" (which nothing ever
# produces). BUSINESS_OWNER has no resolvable field yet — the business's
# contact address lives on BusinessConfig, a translation-time constant
# like email_from_address, not on the lead payload at all — so it's left
# unmapped and rejected below rather than emitting another
# never-populated expression.
_EMAIL_RECIPIENT_FIELD: dict[EmailRecipient, str] = {
    EmailRecipient.CUSTOMER: "email",
}

# email.send has no template engine (same "no template engine yet" scope
# as app.notifications.service.deliver_lead_follow_up_email) — `template`
# is just an id picking one of these fixed (default_subject, body
# expression) pairs, resolved here at translation time. Previously this
# built `$json.templates.{template}`, a path nothing ever populates (the
# lead payload this node actually receives has no `templates` key), so
# the node always sent literal "undefined" text. The body is an n8n
# expression (JS under `{{ }}`) so it can still greet the lead by name
# when store-lead's response has one, mirroring
# deliver_lead_follow_up_email's own `f"Hola {lead.name}," if lead.name
# else "Hola,"` greeting — n8n expressions don't have Python's inline
# conditional, so the equivalent is written as a ternary against
# `$json.name`.
_EMAIL_TEMPLATES: dict[str, tuple[str, str]] = {
    "lead_acknowledgement": (
        "Hemos recibido tu mensaje",
        "={{ `Hola${$json.name ? ' ' + $json.name : ''},\\n\\n"
        "Gracias por contactarnos. Hemos recibido tu mensaje y te responderemos en breve.\\n\\n"
        "Un saludo.` }}",
    ),
}

_TRIGGER_NODE_NAME = "Trigger"
_NODE_X_SPACING = 260


@dataclass(frozen=True)
class N8nTranslationContext:
    """Everything the translator needs that isn't already on the
    WorkflowConfig itself — passed in explicitly (not read from global
    settings) so translation stays a pure, easily-testable function. See
    app.automation.n8n.engine for how this gets built from Settings for
    real use.

    `tenant_id`/`business_id`/`internal_automation_credential_id` are
    optional and additive: when unset, lead.store/notification.send
    nodes translate exactly as before (forwarding `$json` as-is) — a
    context built without them (as every pre-existing test does) keeps
    working unchanged. When set (real usage, and this phase's new
    tests), the callback body is enriched with tenant/business
    ownership and an n8n credential authenticates the call — see
    _internal_callback_node.
    """

    internal_leads_url: str
    internal_notifications_url: str
    email_credential_id: str | None
    tenant_id: str | None = None
    business_id: str | None = None
    internal_automation_credential_id: str | None = None
    # n8n's emailSend node refuses to *activate* without this — unlike
    # the SMTP password (which lives only in the credential
    # `email_credential_id` references), the from-address is itself a
    # node parameter, so it has to be supplied here rather than implied
    # by the credential. Sourced from the same SmtpNotificationSender
    # configuration (settings.smtp_from_address) that already sends
    # internal-notification email — see
    # app.automation.n8n.engine.translation_context_from_settings —
    # rather than a second, n8n-only address setting.
    email_from_address: str | None = None


def translate_workflow(workflow: WorkflowConfig, context: N8nTranslationContext) -> dict[str, Any]:
    source = "website_form" if isinstance(workflow.trigger, LeadSubmittedTrigger) else "webhook"

    n8n_nodes = [_translate_trigger(workflow)]
    for index, node in enumerate(workflow.nodes, start=1):
        n8n_nodes.append(_translate_node(node, context, source=source, x_position=index * _NODE_X_SPACING))

    return {
        "name": workflow.name,
        "nodes": n8n_nodes,
        "connections": _translate_connections(workflow),
        "settings": {},
    }


def _translate_node(
    node: WorkflowNode, context: N8nTranslationContext, *, source: str, x_position: int
) -> dict[str, Any]:
    if isinstance(node, ConditionNode):
        return _if_node(node, x_position)
    return _translate_action_node(node, context, source=source, x_position=x_position)


def _translate_trigger(workflow: WorkflowConfig) -> dict[str, Any]:
    """Both trigger types become an n8n Webhook node — n8n has no native
    concept of `lead.submitted`, only "something posted to a URL". For
    `lead.submitted`, the path is namespaced by the workflow id so each
    business's lead-capture workflow gets its own webhook URL."""
    trigger = workflow.trigger
    if isinstance(trigger, LeadSubmittedTrigger):
        path, method = lead_submitted_webhook_path(workflow.id), "POST"
    elif isinstance(trigger, WebhookTrigger):
        path, method = trigger.path.lstrip("/"), trigger.method
    else:  # pragma: no cover - WorkflowTrigger is a closed union; kept for defensiveness
        raise UnsupportedNodeError(f"unsupported trigger: {trigger!r}")

    return {
        "id": "trigger",
        "name": _TRIGGER_NODE_NAME,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 1,
        "position": [0, 0],
        "parameters": {"path": path, "httpMethod": method},
    }


def _translate_action_node(
    node: ActionNode, context: N8nTranslationContext, *, source: str, x_position: int
) -> dict[str, Any]:
    if node.action is ActionType.HTTP_REQUEST:
        assert isinstance(node.inputs, HttpRequestInputs)
        return _http_request_node(node.id, x_position, node.inputs)

    if node.action is ActionType.LEAD_STORE:
        return _internal_callback_node(
            node.id, x_position, url=context.internal_leads_url, context=context, source=source
        )

    if node.action is ActionType.LEAD_LOOKUP:
        if not context.tenant_id or not context.business_id:
            raise UnsupportedActionError(
                f"node {node.id!r}: lead.lookup needs tenant_id/business_id on the translation "
                "context to scope the request — cannot translate without them."
            )
        return _lead_lookup_node(node.id, x_position, context)

    if node.action is ActionType.LEAD_FOLLOW_UP_EMAIL:
        if not context.tenant_id or not context.business_id:
            raise UnsupportedActionError(
                f"node {node.id!r}: lead.follow_up_email needs tenant_id/business_id on the translation "
                "context to scope the request — cannot translate without them."
            )
        return _lead_follow_up_email_node(node.id, x_position, context)

    if node.action is ActionType.NOTIFICATION_SEND:
        return _internal_callback_node(
            node.id, x_position, url=context.internal_notifications_url, context=context, source=source
        )

    if node.action is ActionType.EMAIL_SEND:
        assert isinstance(node.inputs, EmailSendInputs)
        if not context.email_credential_id:
            raise UnsupportedActionError(
                f"node {node.id!r}: email.send has no n8n SMTP credential configured "
                "(N8N_EMAIL_CREDENTIAL_ID) — cannot translate this action yet."
            )
        if not context.email_from_address:
            raise UnsupportedActionError(
                f"node {node.id!r}: email.send has no from-address configured "
                "(SMTP_FROM_ADDRESS) — n8n's emailSend node refuses to activate "
                "without one — cannot translate this action yet."
            )
        return _email_send_node(node.id, x_position, node.inputs, context.email_credential_id, context.email_from_address)

    if node.action is ActionType.WAIT:
        assert isinstance(node.inputs, WaitInputs)
        return _wait_node(node.id, x_position, node.inputs)

    raise UnsupportedActionError(  # pragma: no cover
        f"node {node.id!r}: action {node.action!r} has no n8n translation yet"
    )


def _http_request_node(node_id: str, x_position: int, inputs: HttpRequestInputs) -> dict[str, Any]:
    """The one action with a real, direct n8n equivalent. Deliberately
    its own function, separate from every other action — the single
    point app.security.ssrf's outbound-URL validation hooks into,
    without touching lead.store/notification.send's fixed internal URLs
    or email.send's credential-only inputs.
    """
    try:
        validate_outbound_url(inputs.url)
    except SSRFValidationError as exc:
        raise UnsupportedActionError(f"node {node_id!r}: {exc}") from exc

    return {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": [x_position, 0],
        "parameters": {
            "url": inputs.url,
            "method": inputs.method,
            "sendHeaders": bool(inputs.headers),
            "headerParameters": {"parameters": [{"name": k, "value": v} for k, v in inputs.headers.items()]},
        },
    }


def _internal_callback_node(
    node_id: str, x_position: int, *, url: str, context: N8nTranslationContext, source: str
) -> dict[str, Any]:
    """lead.store and notification.send have no native n8n node — n8n
    doesn't know what "our" lead storage or internal notifications are.
    Both call back into this API's own /internal/leads and
    /internal/notifications endpoints via a plain HTTP Request node.

    This node's input item has one of two different shapes depending on
    where it sits in the workflow, and the body expression below has to
    handle both:

    * lead.store sits directly downstream of the webhook trigger — n8n's
      Webhook node always wraps a request as `{headers, params, query,
      body}`, so the actual posted fields (name/email/phone/message)
      live at `$json.body`, never at `$json` root.
    * notification.send sits downstream of lead.store instead, so its
      input is *our own* /internal/leads response (LeadResponse) —
      already flat JSON, with no `.body` wrapper.

    `($json.body || $json)` picks whichever of those two shapes is
    actually present, so the same helper works at either position
    without knowing which one it's translating.

    When the context carries tenant_id/business_id (real usage), that
    resolved body is enriched with them plus `source` — the raw webhook
    payload has no idea which business/tenant it belongs to; that
    ownership is known at *translation* time (this workflow was
    generated for one specific business) and gets baked in here as
    plain identifiers, never secrets. Without them (every pre-existing
    test's context), this forwards the resolved body unchanged.

    Authentication to our own endpoint is likewise a credential
    *reference* (an n8n "HTTP Header Auth" credential holding
    INTERNAL_AUTOMATION_TOKEN, configured in n8n out-of-band) — the
    token value itself never appears here, in WorkflowConfig, or in any
    log.
    """
    resolved_body = "($json.body || $json)"
    if context.tenant_id and context.business_id:
        extra = json.dumps({"tenant_id": context.tenant_id, "business_id": context.business_id, "source": source})
        body_expr = f"={{{{ Object.assign({{}}, {resolved_body}, {extra}) }}}}"
    else:
        body_expr = f"={{{{ {resolved_body} }}}}"

    node: dict[str, Any] = {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": [x_position, 0],
        "parameters": {
            "url": url,
            "method": "POST",
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": body_expr,
        },
    }
    _attach_internal_auth(node, context)
    return node


def _attach_internal_auth(node: dict[str, Any], context: N8nTranslationContext) -> None:
    """Shared by every HTTP Request node this translator points at our
    own backend (_internal_callback_node, _lead_lookup_node below) — a
    linked `credentials` entry alone does nothing on n8n's HTTP Request
    node, it only actually attaches a credential to the outgoing
    request when `authentication` opts into it. Without this, the node
    silently defaults to `authentication: "none"` and sends no auth
    header at all, no matter which credential is referenced (confirmed
    live: zero credential-derived headers ever reached our endpoint
    until this was added). No-op when the context has no credential id
    configured yet — same "not configured" shape as every other
    optional context field.
    """
    if not context.internal_automation_credential_id:
        return
    node["parameters"]["authentication"] = "genericCredentialType"
    node["parameters"]["genericAuthType"] = "httpHeaderAuth"
    node["credentials"] = {"httpHeaderAuth": {"id": context.internal_automation_credential_id}}


def _lead_lookup_node(node_id: str, x_position: int, context: N8nTranslationContext) -> dict[str, Any]:
    """lead.lookup has no native n8n node either (same reasoning as
    _internal_callback_node above) — a GET against our own
    /internal/leads/{id} (app.routers.internal_automation.get_lead),
    called after the wait so the response reflects the lead's *current*
    row, not the one captured before waiting.

    The lead's id is read from `$json.lead_id` — NOTIFY_INTERNAL_NODE_
    ID's response (NotificationResponse) already carries it, and the
    Wait node in between passes its input through unchanged, so it's
    still there by the time this node runs (see the generator's own
    docstring for why no extra threading is needed). `tenant_id`/
    `business_id` are known at translation time, same as
    _internal_callback_node's ownership enrichment, and are required
    here (the caller above raises before this function is ever called
    without them) since the endpoint has no other way to scope the
    read.
    """
    node: dict[str, Any] = {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": [x_position, 0],
        "parameters": {
            "url": "=" + context.internal_leads_url + "/{{ $json.lead_id }}",
            "method": "GET",
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {"name": "tenant_id", "value": context.tenant_id},
                    {"name": "business_id", "value": context.business_id},
                ]
            },
        },
    }
    _attach_internal_auth(node, context)
    return node


def _lead_follow_up_email_node(node_id: str, x_position: int, context: N8nTranslationContext) -> dict[str, Any]:
    """lead.follow_up_email has no native n8n node — deliberately *not*
    n8n's own emailSend node either (see the generator's own docstring
    for why EMAIL_SEND doesn't fit this use case). A POST to our own
    /internal/leads/{id}/follow-up-email
    (app.routers.internal_automation.send_lead_follow_up_email), which
    does the actual sending through this backend's own
    NotificationSender/SmtpNotificationSender — the same infrastructure
    internal notifications already use, one SMTP configuration instead
    of a second one living only in n8n.

    The lead id is read from `$json.id` — this node sits downstream of
    lookup-lead (whose response, LeadResponse, has `id`) via two
    ConditionNode hops (check-lead-status, check-lead-has-email),
    neither of which transforms the item n8n's If node just passes its
    input straight through on whichever branch it takes — so the
    lookup's response is still exactly what's on `$json` here. The
    request body carries only tenant_id/business_id (known at
    translation time, like _internal_callback_node's enrichment); the
    recipient and the lead's current status are deliberately not sent
    at all — the endpoint re-derives both itself from the lead's own
    row rather than trusting this payload for them.
    """
    body = json.dumps({"tenant_id": context.tenant_id, "business_id": context.business_id})
    node: dict[str, Any] = {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": [x_position, 0],
        "parameters": {
            "url": "=" + context.internal_leads_url + "/{{ $json.id }}/follow-up-email",
            "method": "POST",
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": f"={{{{ {body} }}}}",
        },
    }
    _attach_internal_auth(node, context)
    return node


def _email_send_node(
    node_id: str, x_position: int, inputs: EmailSendInputs, credential_id: str, from_address: str
) -> dict[str, Any]:
    """`to` is a role (customer/business_owner), resolved here — at
    translation time, not execution time — against the real field name
    on whatever this node's input item actually is (see
    _EMAIL_RECIPIENT_FIELD). `credentials` references an SMTP credential
    n8n already has *by id* — the raw SMTP password never passes through
    this translator or the generated JSON, satisfying "credentials
    referenced by identifier, not value". `fromEmail` is the one address
    this node does need as a literal parameter (n8n requires it to
    activate the node at all) — it comes from the caller-supplied
    `from_address`, itself sourced from the existing
    settings.smtp_from_address, never hardcoded here. `subject`/`text`
    come from _EMAIL_TEMPLATES, keyed by `inputs.template` — see that
    dict's own docstring for why (no template engine, so this is where
    the actual copy lives, same as `to` isn't the literal recipient)."""
    if inputs.to not in _EMAIL_RECIPIENT_FIELD:
        raise UnsupportedActionError(
            f"node {node_id!r}: email.send has no resolvable recipient field for to={inputs.to!r} yet"
        )
    if inputs.template not in _EMAIL_TEMPLATES:
        raise UnsupportedActionError(f"node {node_id!r}: email.send has no content for template {inputs.template!r} yet")

    default_subject, body_expr = _EMAIL_TEMPLATES[inputs.template]
    return {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.emailSend",
        "typeVersion": 2,
        "position": [x_position, 0],
        "parameters": {
            # n8n expression syntax is `={{ ... }}` (literal, not an
            # f-string escaping accident) — {{{{/}}}} in the f-string
            # source is what actually produces the doubled braces.
            "fromEmail": from_address,
            "toEmail": f"={{{{ $json.{_EMAIL_RECIPIENT_FIELD[inputs.to]} }}}}",
            "subject": inputs.subject or default_subject,
            "emailFormat": "text",
            "text": body_expr,
        },
        "credentials": {"smtp": {"id": credential_id}},
    }


def _wait_node(node_id: str, x_position: int, inputs: WaitInputs) -> dict[str, Any]:
    """n8n's native Wait node, defaulting to its "wait for a fixed
    duration" mode (no `resume` parameter needed for that — it's only
    required to pick one of the *other* modes, "resume on webhook" or
    "resume at a specific time", neither of which this codebase uses)."""
    return {
        "id": node_id,
        "name": node_id,
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1.1,
        "position": [x_position, 0],
        "parameters": {"amount": inputs.hours, "unit": "hours"},
    }


def _if_node(node: ConditionNode, x_position: int) -> dict[str, Any]:
    """n8n's native If node (v2). `condition.field` is a dotted path
    documented as relative to "the triggering event's payload"
    (NodeCondition's own docstring) — a leading "lead." names the lead
    entity that path is about, not a literal `$json.lead` wrapper key
    (nothing this translator produces ever nests the lead under a
    `lead` key; see _internal_callback_node's `$json.body || $json`
    resolution, which is always flat), so it's stripped before building
    the n8n expression.
    """
    field = node.condition.field.removeprefix("lead.")
    value = node.condition.value
    value_type = "boolean" if isinstance(value, bool) else "number" if isinstance(value, float) else "string"

    n8n_condition: dict[str, Any] = {
        "id": node.id,
        "leftValue": f"={{{{ $json.{field} }}}}",
        "operator": {"type": value_type, "operation": _CONDITION_OPERATION[node.condition.operator]},
    }
    if value is not None:
        n8n_condition["rightValue"] = value

    return {
        "id": node.id,
        "name": node.id,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": [x_position, 0],
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "typeValidation": "strict"},
                "combinator": "and",
                "conditions": [n8n_condition],
            }
        },
    }


def _translate_connections(workflow: WorkflowConfig) -> dict[str, Any]:
    nodes_by_id = {node.id: node for node in workflow.nodes}
    connections: dict[str, dict[str, list[list[dict[str, Any]]]]] = {}
    for conn in workflow.connections:
        source_name = _TRIGGER_NODE_NAME if conn.source == "trigger" else conn.source
        if conn.source == "trigger":
            output_index, output_count = 0, 1
        else:
            source_outputs = nodes_by_id[conn.source].outputs
            output_index, output_count = source_outputs.index(conn.source_output), len(source_outputs)
        # `main` is pre-sized to *every* output this node declares
        # ("done" for an ActionNode, "true"/"false" for a ConditionNode)
        # the first time it's touched — not just however many indices
        # happen to have a connection — so a condition's unwired "false"
        # branch still comes out as an explicit empty array (matching
        # what n8n's own UI always shows for an If node) rather than
        # being silently absent, and never collides with "true" (index
        # 0) the way one flat bucket would.
        bucket = connections.setdefault(source_name, {}).setdefault("main", [[] for _ in range(output_count)])
        bucket[output_index].append({"node": conn.target, "type": "main", "index": 0})
    return connections
