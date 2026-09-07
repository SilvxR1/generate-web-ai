"""Business intent -> provider-neutral WorkflowConfig. Deterministic, no
AI: one fixed shape (lead capture -> internal notification -> customer
acknowledgement -> follow-up), gated by which AutomationConfig flags are
enabled — the same "generator reads intent, produces a concrete config"
pattern website_generator.generateSiteConfig already established for
WebsiteConfig, applied to the workflow side.
"""

from app.domain.business_config import BusinessConfig
from app.domain.workflow_config.actions import (
    ActionType,
    EmailRecipient,
    EmailSendInputs,
    LeadFollowUpEmailInputs,
    LeadLookupInputs,
    LeadStoreInputs,
    NotificationSendInputs,
    WaitInputs,
)
from app.domain.workflow_config.connections import WorkflowConnection
from app.domain.workflow_config.nodes import ActionNode, ConditionNode, ConditionOperator, NodeCondition, WorkflowNode
from app.domain.workflow_config.triggers import LeadSubmittedTrigger
from app.domain.workflow_config.workflow import WorkflowConfig

STORE_LEAD_NODE_ID = "store-lead"
NOTIFY_INTERNAL_NODE_ID = "notify-internal"
ACKNOWLEDGE_CUSTOMER_NODE_ID = "acknowledge-customer"
WAIT_FOLLOW_UP_NODE_ID = "wait-follow-up"
LOOKUP_LEAD_NODE_ID = "lookup-lead"
CHECK_LEAD_STATUS_NODE_ID = "check-lead-status"
NOTIFY_FOLLOW_UP_NODE_ID = "notify-follow-up"
CHECK_LEAD_HAS_EMAIL_NODE_ID = "check-lead-has-email"
SEND_LEAD_FOLLOW_UP_EMAIL_NODE_ID = "send-lead-follow-up-email"


def generate_lead_capture_workflow(business_config: BusinessConfig) -> WorkflowConfig:
    """lead.submitted -> store lead -> [send internal notification, send
    customer acknowledgement] (the latter two run in parallel off the
    stored lead, each independently optional) -> if follow-up is also
    enabled: wait `automation.follow_up.delay_hours` -> look the lead up
    again (its *current* row, not the one captured before the wait) ->
    check whether it's still NEW -> if so, two things run in parallel:
    an internal follow-up notification (telling the business), and —
    gated by a second, independent check that the lead actually has an
    email — a real follow-up email *to the lead itself*
    (ActionType.LEAD_FOLLOW_UP_EMAIL). If it's already
    CONTACTED/WON/LOST, or it has no email, the relevant condition's
    "false" branch is simply never taken and nothing further runs on
    that side.

    The follow-up chain hangs off NOTIFY_INTERNAL_NODE_ID specifically
    (not off the stored lead directly) — "wait" and "check" only make
    sense once the business has actually been notified, per the product
    flow this generates. So `automation.follow_up.enabled` alone isn't
    enough to produce it: `automation.lead_notifications` must also be
    on, otherwise there is nothing for it to hang off and it's silently
    omitted (no error — same "gated by intent flags" shape as
    customer_acknowledgement below, not a validation failure).

    The condition genuinely evaluates a fresh read: LOOKUP_LEAD_NODE_ID
    (ActionType.LEAD_LOOKUP) fetches the lead by id right before the
    check runs (see app.automation.n8n.translator for how this becomes
    a real HTTP call to our own backend after the wait) — not the
    status captured back when the lead was first stored, which would
    always read NEW regardless of what happened during the wait. The
    lead's id itself needs no special threading here: NOTIFY_INTERNAL_
    NODE_ID's own response already carries it (InternalNotification.
    lead_id), so it's still available on `$json` by the time the lookup
    node runs, the same way every other node in this chain reads its
    input from whatever the previous node returned.

    LEAD_FOLLOW_UP_EMAIL is deliberately its own action, not a reuse of
    EMAIL_SEND: EMAIL_SEND's `to` is a role (customer/business_owner)
    resolved by the translator against whatever field the input item
    actually carries — a fit for "the LeadResponse store-lead just
    returned" (customer_acknowledgement below), but not for "the fresh
    literal address lead.lookup just returned" after a wait, which is a
    different translation-time shape entirely. See
    app.automation.n8n.translator and
    app.notifications.service.deliver_lead_follow_up_email for how this
    action actually sends, through the same NotificationSender
    infrastructure internal notifications and customer_acknowledgement
    already use — never represented as an InternalNotification row,
    which means something different (the business's own team was
    told), not "the lead was emailed".

    Requires `automation.lead_capture` — raises rather than silently
    producing an empty workflow if that intent isn't actually enabled.
    """
    automation = business_config.automation
    if not automation.lead_capture:
        raise ValueError(
            "business_config.automation.lead_capture is not enabled; "
            "there is no lead-capture intent to generate a workflow for."
        )

    profile = business_config.business_profile

    store_lead_node = ActionNode(id=STORE_LEAD_NODE_ID, action=ActionType.LEAD_STORE, inputs=LeadStoreInputs())
    nodes: list[WorkflowNode] = [store_lead_node]
    connections = [WorkflowConnection(source="trigger", target=STORE_LEAD_NODE_ID)]

    if automation.lead_notifications:
        nodes.append(
            ActionNode(
                id=NOTIFY_INTERNAL_NODE_ID,
                action=ActionType.NOTIFICATION_SEND,
                inputs=NotificationSendInputs(template="lead_internal_notification"),
            )
        )
        connections.append(WorkflowConnection(source=STORE_LEAD_NODE_ID, target=NOTIFY_INTERNAL_NODE_ID))

        if automation.follow_up.enabled:
            nodes.append(
                ActionNode(
                    id=WAIT_FOLLOW_UP_NODE_ID,
                    action=ActionType.WAIT,
                    inputs=WaitInputs(hours=automation.follow_up.delay_hours),
                )
            )
            connections.append(WorkflowConnection(source=NOTIFY_INTERNAL_NODE_ID, target=WAIT_FOLLOW_UP_NODE_ID))

            nodes.append(ActionNode(id=LOOKUP_LEAD_NODE_ID, action=ActionType.LEAD_LOOKUP, inputs=LeadLookupInputs()))
            connections.append(WorkflowConnection(source=WAIT_FOLLOW_UP_NODE_ID, target=LOOKUP_LEAD_NODE_ID))

            nodes.append(
                ConditionNode(
                    id=CHECK_LEAD_STATUS_NODE_ID,
                    condition=NodeCondition(field="lead.status", operator=ConditionOperator.EQUALS, value="new"),
                )
            )
            connections.append(WorkflowConnection(source=LOOKUP_LEAD_NODE_ID, target=CHECK_LEAD_STATUS_NODE_ID))

            nodes.append(
                ActionNode(
                    id=NOTIFY_FOLLOW_UP_NODE_ID,
                    action=ActionType.NOTIFICATION_SEND,
                    inputs=NotificationSendInputs(template="lead_follow_up"),
                )
            )
            connections.append(
                WorkflowConnection(
                    source=CHECK_LEAD_STATUS_NODE_ID, source_output="true", target=NOTIFY_FOLLOW_UP_NODE_ID
                )
            )

            # Second, independent branch off the same "still new" check —
            # runs in parallel with the internal notification above, not
            # instead of it. Gated on its own EXISTS condition so a lead
            # with no email simply never reaches the send step.
            nodes.append(
                ConditionNode(
                    id=CHECK_LEAD_HAS_EMAIL_NODE_ID,
                    condition=NodeCondition(field="lead.email", operator=ConditionOperator.EXISTS),
                )
            )
            connections.append(
                WorkflowConnection(
                    source=CHECK_LEAD_STATUS_NODE_ID, source_output="true", target=CHECK_LEAD_HAS_EMAIL_NODE_ID
                )
            )

            nodes.append(
                ActionNode(
                    id=SEND_LEAD_FOLLOW_UP_EMAIL_NODE_ID,
                    action=ActionType.LEAD_FOLLOW_UP_EMAIL,
                    inputs=LeadFollowUpEmailInputs(template="lead_follow_up_email"),
                )
            )
            connections.append(
                WorkflowConnection(
                    source=CHECK_LEAD_HAS_EMAIL_NODE_ID,
                    source_output="true",
                    target=SEND_LEAD_FOLLOW_UP_EMAIL_NODE_ID,
                )
            )

    if automation.customer_acknowledgement:
        nodes.append(
            ActionNode(
                id=ACKNOWLEDGE_CUSTOMER_NODE_ID,
                action=ActionType.EMAIL_SEND,
                inputs=EmailSendInputs(to=EmailRecipient.CUSTOMER, template="lead_acknowledgement"),
            )
        )
        connections.append(WorkflowConnection(source=STORE_LEAD_NODE_ID, target=ACKNOWLEDGE_CUSTOMER_NODE_ID))

    return WorkflowConfig(
        id=f"{profile.slug}-lead-capture",
        name=f"{profile.name} — Lead capture",
        trigger=LeadSubmittedTrigger(),
        nodes=nodes,
        connections=connections,
    )
