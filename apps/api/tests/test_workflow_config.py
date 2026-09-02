"""WorkflowConfig (app.domain.workflow_config): valid workflow, closed
action catalog, graph-integrity validation, credential/secret rejection,
required_capabilities, and the BusinessConfig -> WorkflowConfig
generator — the test bullets from the WorkflowConfig-v1 phase."""

import pytest
from pydantic import ValidationError

from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG, BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical
from app.domain.workflow_config import (
    ActionNode,
    ActionType,
    EmailRecipient,
    EmailSendInputs,
    ErrorHandlingStrategy,
    HttpRequestInputs,
    LeadStoreInputs,
    LeadSubmittedTrigger,
    NotificationSendInputs,
    WorkflowConfig,
    WorkflowConnection,
    generate_lead_capture_workflow,
)


def _minimal_business_config(**automation_overrides: bool) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(name="Sacri Barber", slug="sacri-barber", industry=BusinessVertical.OTHER),
        automation={"lead_capture": True, **automation_overrides},
    )


def _store_node() -> ActionNode:
    return ActionNode(id="store-lead", action=ActionType.LEAD_STORE, inputs=LeadStoreInputs())


# --- valid workflow -----------------------------------------------------


def test_valid_minimal_workflow():
    workflow = WorkflowConfig(
        id="lead-capture",
        name="Lead capture",
        trigger=LeadSubmittedTrigger(),
        nodes=[_store_node()],
        connections=[WorkflowConnection(source="trigger", target="store-lead")],
    )
    assert workflow.version == 1
    assert workflow.error_handling.strategy is ErrorHandlingStrategy.STOP
    assert workflow.required_capabilities == ["lead.store"]


def test_valid_workflow_with_branching_and_condition_node():
    workflow = WorkflowConfig(
        id="lead-capture-branching",
        name="Lead capture with branch",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            _store_node(),
            {"id": "has-email", "type": "condition", "condition": {"field": "lead.email", "operator": "exists"}},
            ActionNode(
                id="ack",
                action=ActionType.EMAIL_SEND,
                inputs=EmailSendInputs(to=EmailRecipient.CUSTOMER, template="lead_acknowledgement"),
            ),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="has-email"),
            WorkflowConnection(source="has-email", source_output="true", target="ack"),
        ],
    )
    assert workflow.required_capabilities == ["email.send", "lead.store"]


# --- closed action catalog ----------------------------------------------


def test_unknown_action_type_rejected():
    with pytest.raises(ValidationError):
        ActionNode(id="do-something", action="shell.run", inputs={"action": "shell.run"})


def test_no_code_execution_action_exists_in_the_catalog():
    assert {a.value for a in ActionType} == {
        "lead.store",
        "lead.lookup",
        "lead.follow_up_email",
        "email.send",
        "notification.send",
        "http.request",
        "wait",
    }


def test_inputs_must_match_declared_action():
    mismatched_inputs = EmailSendInputs(to=EmailRecipient.CUSTOMER, template="x")
    with pytest.raises(ValidationError, match="inputs are configured for action"):
        ActionNode(id="mismatched", action=ActionType.LEAD_STORE, inputs=mismatched_inputs)


# --- duplicate node ids ---------------------------------------------------


def test_duplicate_node_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate node id"):
        WorkflowConfig(
            id="dup",
            name="Duplicate ids",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node(), _store_node()],
            connections=[],
        )


# --- invalid connections ---------------------------------------------------


def test_connection_to_unknown_node_rejected():
    with pytest.raises(ValidationError, match="not a known node id"):
        WorkflowConfig(
            id="bad-target",
            name="Bad target",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node()],
            connections=[WorkflowConnection(source="trigger", target="does-not-exist")],
        )


def test_connection_from_unknown_source_rejected():
    with pytest.raises(ValidationError, match="not 'trigger' or a known node id"):
        WorkflowConfig(
            id="bad-source",
            name="Bad source",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node()],
            connections=[WorkflowConnection(source="ghost-node", target="store-lead")],
        )


def test_connection_targeting_trigger_rejected():
    with pytest.raises(ValidationError, match="cannot be 'trigger'"):
        WorkflowConfig(
            id="targets-trigger",
            name="Targets trigger",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node()],
            connections=[WorkflowConnection(source="store-lead", target="trigger")],
        )


def test_connection_with_unknown_source_output_rejected():
    with pytest.raises(ValidationError, match="has no output"):
        WorkflowConfig(
            id="bad-output",
            name="Bad output",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node()],
            connections=[
                WorkflowConnection(source="trigger", target="store-lead"),
                WorkflowConnection(source="store-lead", source_output="not-a-real-output", target="store-lead"),
            ],
        )


# --- credentials/secrets rejected -----------------------------------------


def test_http_request_rejects_authorization_header():
    with pytest.raises(ValidationError, match="looks like a credential or secret"):
        HttpRequestInputs(url="https://example.com/webhook", headers={"Authorization": "Bearer xyz"})


@pytest.mark.parametrize("header_name", ["api_key", "X-Api-Key", "client_secret", "password", "private_key"])
def test_http_request_rejects_various_secret_like_headers(header_name: str):
    with pytest.raises(ValidationError, match="looks like a credential or secret"):
        HttpRequestInputs(url="https://example.com/webhook", headers={header_name: "shh"})


def test_http_request_rejects_secret_in_query_string():
    with pytest.raises(ValidationError, match="looks like a credential or secret"):
        HttpRequestInputs(url="https://example.com/webhook?api_key=abc123")


def test_http_request_allows_ordinary_headers_and_url():
    inputs = HttpRequestInputs(
        url="https://example.com/webhook?source=website", headers={"Content-Type": "application/json"}
    )
    assert inputs.url.endswith("source=website")


def test_no_action_accepts_arbitrary_extra_fields():
    # extra="forbid" on every *Inputs model closes off smuggling any
    # field (secret-shaped or not) that the closed catalog didn't define.
    with pytest.raises(ValidationError):
        LeadStoreInputs(unexpected_field="anything")


# --- required_capabilities -------------------------------------------------


def test_required_capabilities_reflects_only_action_nodes_used():
    workflow = WorkflowConfig(
        id="two-actions",
        name="Two actions",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            _store_node(),
            ActionNode(
                id="notify",
                action=ActionType.NOTIFICATION_SEND,
                inputs=NotificationSendInputs(template="lead_internal_notification"),
            ),
        ],
        connections=[
            WorkflowConnection(source="trigger", target="store-lead"),
            WorkflowConnection(source="store-lead", target="notify"),
        ],
    )
    assert workflow.required_capabilities == ["lead.store", "notification.send"]


def test_required_capabilities_deduplicated_and_sorted():
    workflow = WorkflowConfig(
        id="repeat-http",
        name="Repeat http",
        trigger=LeadSubmittedTrigger(),
        nodes=[
            ActionNode(id="req-a", action=ActionType.HTTP_REQUEST, inputs=HttpRequestInputs(url="https://a.example.com")),
            ActionNode(id="req-b", action=ActionType.HTTP_REQUEST, inputs=HttpRequestInputs(url="https://b.example.com")),
            _store_node(),
        ],
        connections=[],
    )
    assert workflow.required_capabilities == ["http.request", "lead.store"]


def test_required_capabilities_is_not_settable_directly():
    with pytest.raises(ValidationError):
        WorkflowConfig(
            id="cant-set",
            name="Cant set",
            trigger=LeadSubmittedTrigger(),
            nodes=[_store_node()],
            connections=[],
            required_capabilities=["something.fake"],
        )


# --- BusinessConfig -> WorkflowConfig fixture -------------------------------


def test_generate_lead_capture_workflow_from_reforma_valencia_fixture():
    # The fixture has both lead_notifications and follow_up enabled, so
    # the generated workflow includes the full wait -> lookup ->
    # condition -> [internal notification, email-existence check ->
    # lead email] chain hanging off notify-internal, alongside the
    # parallel customer acknowledgement hanging off store-lead.
    workflow = generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)

    assert workflow.id == "reforma-casa-valencia-lead-capture"
    assert workflow.trigger.type == "lead.submitted"
    node_ids = [n.id for n in workflow.nodes]
    assert node_ids == [
        "store-lead",
        "notify-internal",
        "wait-follow-up",
        "lookup-lead",
        "check-lead-status",
        "notify-follow-up",
        "check-lead-has-email",
        "send-lead-follow-up-email",
        "acknowledge-customer",
    ]
    assert workflow.required_capabilities == [
        "email.send",
        "lead.follow_up_email",
        "lead.lookup",
        "lead.store",
        "notification.send",
        "wait",
    ]

    # store-lead fans out to both notification and acknowledgement in parallel.
    sources_to_store_lead_targets = {c.target for c in workflow.connections if c.source == "store-lead"}
    assert sources_to_store_lead_targets == {"notify-internal", "acknowledge-customer"}

    # notify-internal -> wait -> lookup (fresh read) -> condition, then
    # TWO parallel branches off "still new": the internal notification,
    # and (gated by its own email-existence check) the real email to
    # the lead.
    assert {c.target for c in workflow.connections if c.source == "notify-internal"} == {"wait-follow-up"}
    assert {c.target for c in workflow.connections if c.source == "wait-follow-up"} == {"lookup-lead"}
    assert {c.target for c in workflow.connections if c.source == "lookup-lead"} == {"check-lead-status"}

    still_new_targets = [c for c in workflow.connections if c.source == "check-lead-status"]
    assert {c.target for c in still_new_targets} == {"notify-follow-up", "check-lead-has-email"}
    assert all(c.source_output == "true" for c in still_new_targets)

    has_email_conn = next(c for c in workflow.connections if c.source == "check-lead-has-email")
    assert has_email_conn.source_output == "true"
    assert has_email_conn.target == "send-lead-follow-up-email"

    has_email_node = next(n for n in workflow.nodes if n.id == "check-lead-has-email")
    assert has_email_node.condition.field == "lead.email"
    assert has_email_node.condition.operator == "exists"
    assert has_email_node.condition.value is None


def test_generate_lead_capture_workflow_omits_disabled_steps():
    business_config = _minimal_business_config(lead_notifications=False, customer_acknowledgement=True)
    workflow = generate_lead_capture_workflow(business_config)

    node_ids = {n.id for n in workflow.nodes}
    assert node_ids == {"store-lead", "acknowledge-customer"}
    assert workflow.required_capabilities == ["email.send", "lead.store"]


def test_generate_lead_capture_workflow_requires_lead_capture_enabled():
    business_config = _minimal_business_config(lead_capture=False)

    with pytest.raises(ValueError, match="lead_capture is not enabled"):
        generate_lead_capture_workflow(business_config)


def test_workflow_config_json_round_trip():
    workflow = generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)
    dumped = workflow.model_dump(mode="json")

    # required_capabilities is a computed, output-only field (serialized
    # for a consumer like a future AutomationEngine to read, same as
    # test_required_capabilities_is_not_settable_directly establishes) —
    # not a settable input, so it's excluded before re-validating, same
    # as any other read-only/derived API field would be.
    dumped.pop("required_capabilities")
    restored = WorkflowConfig.model_validate(dumped)

    assert restored == workflow
    assert restored.required_capabilities == workflow.required_capabilities
