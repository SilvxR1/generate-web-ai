"""WorkflowConfig -> n8n JSON translation: correctness, the unsupported
cases ("no simules éxito"), and that secrets never appear in the
generated payload — the "translation correcta" / "unsupported action
rejected" / "secrets no aparecen en payload" test bullets."""

import json

import pytest

from app.automation.errors import UnsupportedActionError
from app.automation.n8n import N8nTranslationContext, translate_workflow
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.workflow_config import (
    ActionNode,
    ActionType,
    ConditionNode,
    EmailRecipient,
    EmailSendInputs,
    HttpRequestInputs,
    LeadStoreInputs,
    LeadSubmittedTrigger,
    WorkflowConfig,
    WorkflowConnection,
    generate_lead_capture_workflow,
)

CONTEXT = N8nTranslationContext(
    internal_leads_url="http://localhost:8000/internal/leads",
    internal_notifications_url="http://localhost:8000/internal/notifications",
    email_credential_id="n8n-smtp-credential-id",
    email_from_address="noreply@example.com",
    # Real usage always carries these (see
    # app.automation.n8n.engine.translation_context_from_settings) — and
    # the reforma-valencia fixture below now includes a lead.lookup
    # node, which needs them to translate at all.
    tenant_id="11111111-1111-1111-1111-111111111111",
    business_id="22222222-2222-2222-2222-222222222222",
)


def _lead_capture_workflow():
    return generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)


# --- translation correctness ------------------------------------------------


def test_translates_trigger_to_webhook_node_namespaced_by_workflow_id():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)

    trigger_node = payload["nodes"][0]
    assert trigger_node["type"] == "n8n-nodes-base.webhook"
    assert trigger_node["parameters"]["path"] == "lead-submitted/reforma-casa-valencia-lead-capture"
    assert trigger_node["parameters"]["httpMethod"] == "POST"


def test_translates_lead_store_and_notification_send_to_internal_http_calls():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    nodes_by_id = {n["id"]: n for n in payload["nodes"]}

    assert nodes_by_id["store-lead"]["type"] == "n8n-nodes-base.httpRequest"
    assert nodes_by_id["store-lead"]["parameters"]["url"] == CONTEXT.internal_leads_url
    assert nodes_by_id["notify-internal"]["parameters"]["url"] == CONTEXT.internal_notifications_url


def test_internal_callback_body_prefers_the_webhook_bodys_nested_fields():
    # n8n's Webhook node always wraps a request as {headers, params,
    # query, body} — the real posted fields live at $json.body, not
    # $json root. notify-internal sits downstream of store-lead instead
    # (whose input is our own flat /internal/leads response), so the
    # same expression must fall back to plain $json there. Deliberately
    # a *local* unenriched context (no tenant_id/business_id) — this is
    # specifically testing the unenriched `$json.body || $json` shape,
    # which the module-level CONTEXT no longer produces now that it
    # carries ownership (see test_internal_callback_body_enriches_the_
    # resolved_fields_with_ownership for that case).
    unenriched_context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
    )
    workflow = WorkflowConfig(
        id="lead-capture",
        name="Lead capture",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ActionNode(
                id="notify-internal",
                action=ActionType.NOTIFICATION_SEND,
                inputs={"action": "notification.send", "template": "lead_internal_notification"},
            ),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="notify-internal"),
        ],
    )
    payload = translate_workflow(workflow, unenriched_context)
    nodes_by_id = {n["id"]: n for n in payload["nodes"]}

    for node_id in ("store-lead", "notify-internal"):
        body_expr = nodes_by_id[node_id]["parameters"]["jsonBody"]
        assert "$json.body || $json" in body_expr

    assert nodes_by_id["store-lead"]["parameters"]["jsonBody"] == "={{ ($json.body || $json) }}"


def test_internal_callback_body_enriches_the_resolved_fields_with_ownership():
    context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id="n8n-smtp-credential-id",
        email_from_address=CONTEXT.email_from_address,
        tenant_id="11111111-1111-1111-1111-111111111111",
        business_id="22222222-2222-2222-2222-222222222222",
    )
    payload = translate_workflow(_lead_capture_workflow(), context)
    store_node = next(n for n in payload["nodes"] if n["id"] == "store-lead")
    body_expr = store_node["parameters"]["jsonBody"]

    assert body_expr.startswith("={{ Object.assign({}, ($json.body || $json), ")
    assert '"tenant_id": "11111111-1111-1111-1111-111111111111"' in body_expr
    assert '"business_id": "22222222-2222-2222-2222-222222222222"' in body_expr
    assert '"source": "website_form"' in body_expr


def test_translates_email_send_with_credential_reference_not_value():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    email_node = next(n for n in payload["nodes"] if n["type"] == "n8n-nodes-base.emailSend")

    assert email_node["credentials"] == {"smtp": {"id": "n8n-smtp-credential-id"}}
    # acknowledge-customer sits directly downstream of store-lead, whose
    # translated httpRequest node returns our own /internal/leads response
    # (LeadResponse) as $json verbatim — so "customer" must resolve to
    # that response's actual `email` field, never a literal "customer"
    # key nothing ever produces (see translator._EMAIL_RECIPIENT_FIELD).
    assert email_node["parameters"]["toEmail"] == "={{ $json.email }}"


def test_email_send_subject_and_body_are_never_undefined():
    # Regression test: this node used to build `text` from
    # `$json.templates.{template}`, a path nothing ever populates, so
    # every acknowledgement email n8n actually sent had literal
    # "undefined" text (and, before the toEmail fix above, no resolvable
    # recipient either). Both must now be real, non-empty content
    # resolved at translation time, not deferred to a nonexistent
    # runtime field.
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    email_node = next(n for n in payload["nodes"] if n["type"] == "n8n-nodes-base.emailSend")

    assert email_node["parameters"]["subject"]
    assert "undefined" not in email_node["parameters"]["subject"]
    assert email_node["parameters"]["text"]
    assert "$json.templates" not in email_node["parameters"]["text"]
    assert "undefined" not in email_node["parameters"]["text"]


def test_email_send_node_always_carries_a_from_address():
    # n8n refuses to *activate* an emailSend node without `fromEmail`
    # ("Missing or invalid required parameters: fromEmail") — every
    # translated email.send node must carry a literal, non-empty value
    # for it, sourced from the context (ultimately
    # settings.smtp_from_address), never left unset.
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    email_node = next(n for n in payload["nodes"] if n["type"] == "n8n-nodes-base.emailSend")

    assert email_node["parameters"]["fromEmail"] == CONTEXT.email_from_address
    assert email_node["parameters"]["fromEmail"]


def test_email_send_rejected_without_configured_from_address():
    workflow = WorkflowConfig(
        id="needs-email",
        name="Needs email",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="ack", action=ActionType.EMAIL_SEND, inputs=EmailSendInputs(to=EmailRecipient.CUSTOMER, template="x")
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="ack")],
    )
    context_without_from_address = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
        email_from_address=None,
    )

    with pytest.raises(UnsupportedActionError, match="no from-address configured"):
        translate_workflow(workflow, context_without_from_address)


def test_translates_http_request_action_directly():
    workflow = WorkflowConfig(
        id="http-demo",
        name="HTTP demo",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="call-crm",
                action=ActionType.HTTP_REQUEST,
                inputs=HttpRequestInputs(
                    url="https://example.com/leads", method="POST", headers={"X-Source": "website"}
                ),
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="call-crm")],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "call-crm")

    assert node["type"] == "n8n-nodes-base.httpRequest"
    assert node["parameters"]["url"] == "https://example.com/leads"
    assert node["parameters"]["headerParameters"]["parameters"] == [{"name": "X-Source", "value": "website"}]


def test_translates_connections_keyed_by_node_name_including_trigger():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)

    assert payload["connections"]["Trigger"]["main"][0] == [{"node": "store-lead", "type": "main", "index": 0}]
    targets = {edge["node"] for edge in payload["connections"]["store-lead"]["main"][0]}
    assert targets == {"notify-internal", "acknowledge-customer"}


def test_translated_workflow_omits_active_field():
    # n8n's create/update workflow endpoints treat `active` as
    # read-only ("request/body/active is read-only") — sending it at
    # all, even `false`, is rejected outright. Activation happens only
    # via the dedicated N8nAutomationEngine.activate_workflow() call
    # (POST /workflows/{id}/activate), never in this payload.
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    assert "active" not in payload


# --- unsupported cases rejected, not silently faked -------------------------


def test_condition_node_translates_to_native_if_node():
    workflow = WorkflowConfig(
        id="has-condition",
        name="Has condition",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ConditionNode(id="check", condition={"field": "lead.status", "operator": "equals", "value": "new"}),
        ],
        connections=[WorkflowConnection(source="trigger", target="store-lead")],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "check")

    assert node["type"] == "n8n-nodes-base.if"
    condition = node["parameters"]["conditions"]["conditions"][0]
    # "lead." is stripped — nothing this translator produces wraps the
    # lead entity under a `lead` key, it's always flat at $json root.
    assert condition["leftValue"] == "={{ $json.status }}"
    assert condition["operator"] == {"type": "string", "operation": "equals"}
    assert condition["rightValue"] == "new"


def test_condition_node_true_false_outputs_route_to_different_connection_buckets():
    workflow = WorkflowConfig(
        id="has-condition",
        name="Has condition",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ConditionNode(id="check", condition={"field": "lead.status", "operator": "equals", "value": "new"}),
            ActionNode(
                id="notify-still-new",
                action=ActionType.NOTIFICATION_SEND,
                inputs={"action": "notification.send", "template": "still_new"},
            ),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="check"),
            WorkflowConnection(source="check", source_output="true", target="notify-still-new"),
        ],
    )

    payload = translate_workflow(workflow, CONTEXT)

    check_connections = payload["connections"]["check"]["main"]
    assert [edge["node"] for edge in check_connections[0]] == ["notify-still-new"]
    # "false" (index 1) has no wired target in this workflow, but the
    # bucket itself must exist and stay empty — never silently merged
    # into index 0, which would route both branches the same way.
    assert check_connections[1] == []


def test_wait_action_translates_to_native_wait_node():
    workflow = WorkflowConfig(
        id="has-wait",
        name="Has wait",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ActionNode(id="pause", action=ActionType.WAIT, inputs={"action": "wait", "hours": 48}),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="pause"),
        ],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "pause")

    assert node["type"] == "n8n-nodes-base.wait"
    assert node["parameters"] == {"amount": 48, "unit": "hours"}


def test_follow_up_chain_from_reforma_valencia_fixture_has_no_code_or_shell_node():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)

    node_types = {n["type"] for n in payload["nodes"]}
    assert "n8n-nodes-base.wait" in node_types
    assert "n8n-nodes-base.if" in node_types
    for forbidden in ("n8n-nodes-base.code", "n8n-nodes-base.function", "n8n-nodes-base.executeCommand"):
        assert forbidden not in node_types

    # wait -> lookup (fresh GET) -> condition, then two parallel
    # branches off "still new": the internal notification, and (gated
    # by its own email-existence check) the real email to the lead.
    wait_targets = {edge["node"] for edge in payload["connections"]["notify-internal"]["main"][0]}
    assert wait_targets == {"wait-follow-up"}
    lookup_targets = {edge["node"] for edge in payload["connections"]["wait-follow-up"]["main"][0]}
    assert lookup_targets == {"lookup-lead"}
    condition_source = {edge["node"] for edge in payload["connections"]["lookup-lead"]["main"][0]}
    assert condition_source == {"check-lead-status"}
    condition_targets = payload["connections"]["check-lead-status"]["main"]
    assert {edge["node"] for edge in condition_targets[0]} == {"notify-follow-up", "check-lead-has-email"}
    assert condition_targets[1] == []

    has_email_targets = payload["connections"]["check-lead-has-email"]["main"]
    assert [edge["node"] for edge in has_email_targets[0]] == ["send-lead-follow-up-email"]
    assert has_email_targets[1] == []

    lookup_node = next(n for n in payload["nodes"] if n["id"] == "lookup-lead")
    assert lookup_node["type"] == "n8n-nodes-base.httpRequest"
    assert lookup_node["parameters"]["method"] == "GET"

    email_node = next(n for n in payload["nodes"] if n["id"] == "send-lead-follow-up-email")
    assert email_node["type"] == "n8n-nodes-base.httpRequest"
    assert email_node["parameters"]["method"] == "POST"
    # Never n8n's native emailSend node — no separate SMTP credential
    # duplicated here, this goes through our own backend instead.
    assert email_node["type"] != "n8n-nodes-base.emailSend"


def test_lead_lookup_translates_to_get_request_with_lead_id_from_json_and_scoping_query_params():
    workflow = WorkflowConfig(
        id="has-lookup",
        name="Has lookup",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ActionNode(id="lookup", action=ActionType.LEAD_LOOKUP, inputs={"action": "lead.lookup"}),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="lookup"),
        ],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "lookup")

    assert node["type"] == "n8n-nodes-base.httpRequest"
    assert node["parameters"]["method"] == "GET"
    # The lead's id is read from whatever the previous node's response
    # carries (an n8n expression, resolved at execution time) — never a
    # literal id baked in at translation time, since the lead doesn't
    # exist until the workflow actually runs.
    assert node["parameters"]["url"] == "=http://localhost:8000/internal/leads/{{ $json.lead_id }}"
    assert node["parameters"]["sendQuery"] is True
    query_params = {p["name"]: p["value"] for p in node["parameters"]["queryParameters"]["parameters"]}
    assert query_params == {"tenant_id": CONTEXT.tenant_id, "business_id": CONTEXT.business_id}


def test_lead_lookup_attaches_the_same_internal_credential_as_other_callbacks():
    context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
        tenant_id=CONTEXT.tenant_id,
        business_id=CONTEXT.business_id,
        internal_automation_credential_id="n8n-internal-auth-credential-id",
    )
    workflow = WorkflowConfig(
        id="has-lookup",
        name="Has lookup",
        trigger=LeadSubmittedTrigger(),
        nodes=[ActionNode(id="lookup", action=ActionType.LEAD_LOOKUP, inputs={"action": "lead.lookup"})],
        connections=[WorkflowConnection(source="trigger", target="lookup")],
    )

    payload = translate_workflow(workflow, context)
    node = next(n for n in payload["nodes"] if n["id"] == "lookup")

    assert node["parameters"]["authentication"] == "genericCredentialType"
    assert node["credentials"] == {"httpHeaderAuth": {"id": "n8n-internal-auth-credential-id"}}


def test_lead_lookup_rejected_without_tenant_and_business_on_context():
    unscoped_context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
    )
    workflow = WorkflowConfig(
        id="has-lookup",
        name="Has lookup",
        trigger=LeadSubmittedTrigger(),
        nodes=[ActionNode(id="lookup", action=ActionType.LEAD_LOOKUP, inputs={"action": "lead.lookup"})],
        connections=[WorkflowConnection(source="trigger", target="lookup")],
    )

    with pytest.raises(UnsupportedActionError, match="lead.lookup needs tenant_id/business_id"):
        translate_workflow(workflow, unscoped_context)


def test_lead_follow_up_email_translates_to_post_request_never_native_email_send():
    workflow = WorkflowConfig(
        id="has-follow-up-email",
        name="Has follow-up email",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="send-email",
                action=ActionType.LEAD_FOLLOW_UP_EMAIL,
                inputs={"action": "lead.follow_up_email", "template": "lead_follow_up_email"},
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="send-email")],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "send-email")

    assert node["type"] == "n8n-nodes-base.httpRequest"
    assert node["parameters"]["method"] == "POST"
    # The lead id (not lead_id) is read from whatever the previous
    # node's response carries — resolved at execution time, never a
    # literal id baked in at translation time.
    assert node["parameters"]["url"] == "=http://localhost:8000/internal/leads/{{ $json.id }}/follow-up-email"
    body_str = node["parameters"]["jsonBody"].removeprefix("=").strip().removeprefix("{{").removesuffix("}}").strip()
    body = json.loads(body_str)
    assert body == {"tenant_id": CONTEXT.tenant_id, "business_id": CONTEXT.business_id}
    # No recipient, no lead status, no message content in the payload —
    # the endpoint re-derives all of that itself.
    assert set(body.keys()) == {"tenant_id", "business_id"}


def test_lead_follow_up_email_attaches_the_same_internal_credential_as_other_callbacks():
    context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
        tenant_id=CONTEXT.tenant_id,
        business_id=CONTEXT.business_id,
        internal_automation_credential_id="n8n-internal-auth-credential-id",
    )
    workflow = WorkflowConfig(
        id="has-follow-up-email",
        name="Has follow-up email",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="send-email",
                action=ActionType.LEAD_FOLLOW_UP_EMAIL,
                inputs={"action": "lead.follow_up_email", "template": "lead_follow_up_email"},
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="send-email")],
    )

    payload = translate_workflow(workflow, context)
    node = next(n for n in payload["nodes"] if n["id"] == "send-email")

    assert node["parameters"]["authentication"] == "genericCredentialType"
    assert node["credentials"] == {"httpHeaderAuth": {"id": "n8n-internal-auth-credential-id"}}


def test_lead_follow_up_email_rejected_without_tenant_and_business_on_context():
    unscoped_context = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=CONTEXT.email_credential_id,
    )
    workflow = WorkflowConfig(
        id="has-follow-up-email",
        name="Has follow-up email",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="send-email",
                action=ActionType.LEAD_FOLLOW_UP_EMAIL,
                inputs={"action": "lead.follow_up_email", "template": "lead_follow_up_email"},
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="send-email")],
    )

    with pytest.raises(UnsupportedActionError, match="lead.follow_up_email needs tenant_id/business_id"):
        translate_workflow(workflow, unscoped_context)


def test_condition_exists_operator_translates_without_a_right_value():
    workflow = WorkflowConfig(
        id="has-exists-condition",
        name="Has exists condition",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs()),
            ConditionNode(id="has-email", condition={"field": "lead.email", "operator": "exists"}),
        ],
        connections=[WorkflowConnection(source="trigger", target="store-lead")],
    )

    payload = translate_workflow(workflow, CONTEXT)
    node = next(n for n in payload["nodes"] if n["id"] == "has-email")
    condition = node["parameters"]["conditions"]["conditions"][0]

    assert condition["leftValue"] == "={{ $json.email }}"
    assert condition["operator"]["operation"] == "exists"
    assert "rightValue" not in condition


def test_email_send_rejected_without_configured_credential():
    workflow = WorkflowConfig(
        id="needs-email",
        name="Needs email",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(
                id="ack", action=ActionType.EMAIL_SEND, inputs=EmailSendInputs(to=EmailRecipient.CUSTOMER, template="x")
            )
        ],
        connections=[WorkflowConnection(source="trigger", target="ack")],
    )
    context_without_credential = N8nTranslationContext(
        internal_leads_url=CONTEXT.internal_leads_url,
        internal_notifications_url=CONTEXT.internal_notifications_url,
        email_credential_id=None,
    )

    with pytest.raises(UnsupportedActionError, match="no n8n SMTP credential configured"):
        translate_workflow(workflow, context_without_credential)


# --- no secrets in the generated payload ------------------------------------


def test_no_secret_shaped_content_in_translated_payload():
    payload = translate_workflow(_lead_capture_workflow(), CONTEXT)
    serialized = json.dumps(payload).lower()

    for forbidden in ("password", "smtp_password", "api_key=", "authorization", "-----begin"):
        assert forbidden not in serialized

    # The only credential-shaped thing present is a reference by id.
    email_node = next(n for n in payload["nodes"] if n["type"] == "n8n-nodes-base.emailSend")
    assert email_node["credentials"]["smtp"] == {"id": CONTEXT.email_credential_id}
