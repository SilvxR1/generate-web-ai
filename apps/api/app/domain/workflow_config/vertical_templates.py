"""BusinessConfig -> vertical -> recommended AutomationConfig ->
WorkflowConfig. A thin, declarative layer on top of the *existing*
generator — not a second workflow engine. generate_recommended_workflow
below does nothing generate_lead_capture_workflow doesn't already do:
it builds an AutomationConfig from a per-vertical template and hands it
to that same generator, exactly like any hand-configured
BusinessConfig.automation would be. Every node/connection/translation
concern still lives in generator.py and app.automation.n8n.translator,
untouched.

BusinessConfig stays the source of truth throughout: the vertical this
reads is BusinessConfig.business_profile.industry itself, never a
separate parameter passed alongside it, and every other section of the
config (profile, contact, lead sources, ...) flows through this
function unchanged — only `automation` is replaced with the vertical's
recommendation. This is a pure, read-only function: it never persists
anything or mutates the BusinessConfig a caller already has stored:
"recommended" is exactly that, a suggestion for a caller to act on
(e.g. proposing it to a human, or seeding a new business's config)
rather than this module's own opinion silently overriding one.

MVP scope, deliberately: three named verticals (home services,
restaurant, professional services) plus one generic fallback for
everything else, each varying only the four things
generate_lead_capture_workflow already knows how to vary
(lead_notifications, customer_acknowledgement, follow_up.enabled,
follow_up.delay_hours) — lead_capture itself is always on, the fixed
base every template builds from. No WhatsApp, booking, payments, or
CRM here; adding a vertical means adding one more AutomationTemplate
entry below, never new branching logic.
"""

from dataclasses import dataclass

from app.domain.business_config import AutomationConfig, BusinessConfig, FollowUpConfig
from app.domain.enums import BusinessVertical
from app.domain.workflow_config.generator import generate_lead_capture_workflow
from app.domain.workflow_config.workflow import WorkflowConfig


@dataclass(frozen=True)
class AutomationTemplate:
    """Declarative and closed on purpose — four fields, nothing else,
    no logic. A vertical's whole recommendation is these four values;
    generate_recommended_workflow is the only place that turns one into
    an actual WorkflowConfig."""

    lead_notifications: bool
    customer_acknowledgement: bool
    follow_up_enabled: bool
    follow_up_delay_hours: int = 24


# Each comment states the product reasoning, not just the values, so a
# future vertical can follow the same judgment rather than guessing.

_HOME_SERVICES_TEMPLATE = AutomationTemplate(
    # Reformas/home services: leads are often urgent (a leak, a broken
    # boiler) and deal sizes justify a human follow-up if the team
    # hasn't reached out within a working day.
    lead_notifications=True,
    customer_acknowledgement=True,
    follow_up_enabled=True,
    follow_up_delay_hours=24,
)

_RESTAURANT_TEMPLATE = AutomationTemplate(
    # Restaurant leads (reservation/inquiry requests) are usually
    # time-sensitive on the scale of hours, not days — an async
    # follow-up a day later would land after the moment has passed, so
    # this MVP leaves it off rather than automate something unhelpful.
    lead_notifications=True,
    customer_acknowledgement=True,
    follow_up_enabled=False,
    follow_up_delay_hours=24,
)

_PROFESSIONAL_SERVICES_TEMPLATE = AutomationTemplate(
    # Professional services (legal, consulting, accounting — the
    # closest existing BusinessVertical is B2B_SERVICES) typically have
    # longer sales cycles; a longer delay gives the team a realistic
    # window to respond before an automated nudge.
    lead_notifications=True,
    customer_acknowledgement=True,
    follow_up_enabled=True,
    follow_up_delay_hours=48,
)

_FALLBACK_TEMPLATE = AutomationTemplate(
    # Unrecognized/unmapped vertical: deliberately conservative — tell
    # the business about the lead, but don't presume a customer-facing
    # message or a follow-up cadence for a business this MVP has no
    # specific recommendation for yet.
    lead_notifications=True,
    customer_acknowledgement=False,
    follow_up_enabled=False,
    follow_up_delay_hours=24,
)

_TEMPLATES_BY_VERTICAL: dict[BusinessVertical, AutomationTemplate] = {
    BusinessVertical.HOME_RENOVATION: _HOME_SERVICES_TEMPLATE,
    BusinessVertical.RESTAURANT: _RESTAURANT_TEMPLATE,
    BusinessVertical.B2B_SERVICES: _PROFESSIONAL_SERVICES_TEMPLATE,
}


def recommended_automation_template(vertical: BusinessVertical) -> AutomationTemplate:
    """The one lookup this module needs — a plain dict `.get` with a
    generic fallback, not a chain of if/elif branches, so recognizing a
    new vertical later is a one-line registry addition."""
    return _TEMPLATES_BY_VERTICAL.get(vertical, _FALLBACK_TEMPLATE)


def _automation_config_from_template(template: AutomationTemplate) -> AutomationConfig:
    return AutomationConfig(
        lead_capture=True,
        lead_notifications=template.lead_notifications,
        customer_acknowledgement=template.customer_acknowledgement,
        follow_up=FollowUpConfig(enabled=template.follow_up_enabled, delay_hours=template.follow_up_delay_hours),
    )


def generate_recommended_workflow(business_config: BusinessConfig) -> WorkflowConfig:
    """BusinessConfig -> vertical -> template -> WorkflowConfig, reusing
    generate_lead_capture_workflow for the actual node graph. Every
    section of `business_config` other than `automation` (profile,
    contact, lead sources, ...) is passed through completely unchanged;
    only `automation` is replaced with what
    recommended_automation_template(business_config.business_profile.industry)
    recommends — this function's entire purpose, so it always applies
    the recommendation rather than merging with whatever automation
    settings the input happened to carry.
    """
    template = recommended_automation_template(business_config.business_profile.industry)
    recommended_automation = _automation_config_from_template(template)
    return generate_lead_capture_workflow(business_config.model_copy(update={"automation": recommended_automation}))
