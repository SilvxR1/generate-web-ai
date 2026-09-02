"""app.domain.workflow_config.vertical_templates: the 3 named verticals'
recommended AutomationTemplate, the generic fallback for anything else,
and that generate_recommended_workflow produces exactly the
WorkflowConfig each vertical's template describes — reusing
generate_lead_capture_workflow unchanged, never a second workflow
engine."""

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical
from app.domain.workflow_config import (
    AutomationTemplate,
    generate_recommended_workflow,
    recommended_automation_template,
)


def _business_config(vertical: BusinessVertical, **automation_overrides: bool) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(name="Mi Negocio", slug="mi-negocio", industry=vertical),
        automation={"lead_capture": False, **automation_overrides},
    )


# --- recommended_automation_template registry -------------------------


def test_home_services_template():
    template = recommended_automation_template(BusinessVertical.HOME_RENOVATION)

    assert template == AutomationTemplate(
        lead_notifications=True, customer_acknowledgement=True, follow_up_enabled=True, follow_up_delay_hours=24
    )


def test_restaurant_template():
    template = recommended_automation_template(BusinessVertical.RESTAURANT)

    assert template == AutomationTemplate(
        lead_notifications=True, customer_acknowledgement=True, follow_up_enabled=False, follow_up_delay_hours=24
    )


def test_professional_services_template():
    # "servicios profesionales" maps onto the closest existing
    # BusinessVertical: B2B_SERVICES.
    template = recommended_automation_template(BusinessVertical.B2B_SERVICES)

    assert template == AutomationTemplate(
        lead_notifications=True, customer_acknowledgement=True, follow_up_enabled=True, follow_up_delay_hours=48
    )


def test_fallback_template_for_unmapped_verticals():
    fallback = AutomationTemplate(
        lead_notifications=True, customer_acknowledgement=False, follow_up_enabled=False, follow_up_delay_hours=24
    )

    for vertical in (
        BusinessVertical.OTHER,
        BusinessVertical.CLINIC,
        BusinessVertical.REAL_ESTATE,
        BusinessVertical.AGENCY,
        BusinessVertical.ECOMMERCE,
        BusinessVertical.HOTEL,
    ):
        assert recommended_automation_template(vertical) == fallback


# --- generate_recommended_workflow -------------------------------------


def test_home_services_workflow_has_the_full_follow_up_chain_with_a_24h_wait():
    workflow = generate_recommended_workflow(_business_config(BusinessVertical.HOME_RENOVATION))

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
    wait_node = next(n for n in workflow.nodes if n.id == "wait-follow-up")
    assert wait_node.inputs.hours == 24


def test_restaurant_workflow_has_no_follow_up_chain():
    workflow = generate_recommended_workflow(_business_config(BusinessVertical.RESTAURANT))

    node_ids = [n.id for n in workflow.nodes]
    assert node_ids == ["store-lead", "notify-internal", "acknowledge-customer"]
    assert workflow.required_capabilities == ["email.send", "lead.store", "notification.send"]


def test_professional_services_workflow_has_the_full_follow_up_chain_with_a_48h_wait():
    workflow = generate_recommended_workflow(_business_config(BusinessVertical.B2B_SERVICES))

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
    wait_node = next(n for n in workflow.nodes if n.id == "wait-follow-up")
    assert wait_node.inputs.hours == 48


def test_unrecognized_vertical_falls_back_to_the_generic_minimal_workflow():
    workflow = generate_recommended_workflow(_business_config(BusinessVertical.HOTEL))

    # Fallback: notify the team, nothing else — no customer email, no
    # follow-up chain, for a vertical this MVP has no opinion about.
    node_ids = [n.id for n in workflow.nodes]
    assert node_ids == ["store-lead", "notify-internal"]
    assert workflow.required_capabilities == ["lead.store", "notification.send"]


def test_recommendation_overrides_whatever_automation_the_input_already_had():
    # The whole point of "recommended": the vertical's template always
    # wins over the input's own automation section, never merges with
    # it — proven here with a restaurant config that pre-sets
    # customer_acknowledgement=False (the opposite of the template).
    business_config = _business_config(
        BusinessVertical.RESTAURANT, lead_capture=True, customer_acknowledgement=False, lead_notifications=False
    )

    workflow = generate_recommended_workflow(business_config)

    node_ids = {n.id for n in workflow.nodes}
    assert node_ids == {"store-lead", "notify-internal", "acknowledge-customer"}


def test_recommendation_never_fails_on_lead_capture_disabled_input():
    # generate_lead_capture_workflow raises if automation.lead_capture
    # is off — the recommendation always forces it on, so this never
    # bubbles up here no matter what the input carried.
    business_config = _business_config(BusinessVertical.HOME_RENOVATION, lead_capture=False)

    workflow = generate_recommended_workflow(business_config)

    assert workflow.nodes  # did not raise


def test_recommendation_preserves_the_business_profile_unchanged():
    business_config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Reformas Turia", slug="reformas-turia", industry=BusinessVertical.HOME_RENOVATION
        ),
        automation={"lead_capture": False},
    )

    workflow = generate_recommended_workflow(business_config)

    assert workflow.id == "reformas-turia-lead-capture"
    assert workflow.name == "Reformas Turia — Lead capture"
