"""BusinessAnalysisOutput -> BusinessAnalysisResult: the provider-agnostic
mapping from an LLM's raw structured output to an actual, schema-validated
BusinessConfig proposal. Never invents a fact the raw output didn't
provide; every field that can't be safely assembled becomes a
missing_information/questions entry instead of a guess.

Several things are deliberately NOT modeled as a real BusinessConfig
field here, by design rather than oversight:

- Brand colors/typography, communication-channel preferences, and the
  finer automation intents (customer acknowledgement, follow-up):
  BusinessAnalysisOutput doesn't extract these at all (see its own
  docstring) — Anthropic's structured-output call rejects a schema rich
  enough to carry them alongside everything else. A human still sets
  all of these in the review step; only the automated proposal for them
  is gone. `communications`/the dropped automation fields are simply
  left at BusinessConfig's own defaults below.
- Anything resembling a credential/secret: BusinessConfig has no field
  that could hold one (see communication.py/integrations.py's own
  boundary notes) — there is structurally nowhere for one to go, so no
  special-casing is needed here.

Every BusinessProfile/BusinessConfig construction below is wrapped in a
final `except ValidationError` — defense in depth, not the primary
mechanism: by the time we get there, the code above should have already
turned anything invalid into a missing_information/questions entry.
"""

import unicodedata

from pydantic import ValidationError

from app.analysis.analyzer import BusinessAnalysisResult
from app.analysis.errors import InvalidAnalysisOutputError
from app.analysis.schema import (
    BusinessAnalysisOutput,
    RawContactInfo,
    RawLocation,
    RawServiceOffering,
)
from app.domain.business_config import (
    SLUG_PATTERN,
    AutomationConfig,
    BusinessConfig,
    BusinessProfile,
    ContactInfo,
    LeadManagementConfig,
    Location,
    ServiceOffering,
)
from app.domain.enums import BusinessVertical, LeadSource

_MAX_SLUG_LENGTH = 100


def slugify(text: str) -> str:
    """Deterministic name -> slug derivation (accent-stripping, lowercase,
    non-alphanumeric runs collapsed to one hyphen). This is a formatting
    transform of a fact the briefing already gave us (the business name),
    not an invented one — the slug still has to satisfy
    BusinessProfile.slug's own SLUG_PATTERN, checked at the call site."""
    ascii_only = text if text.isascii() else _strip_accents(text)
    hyphenated = "".join(ch if (ch.isalnum() and ch.isascii()) else "-" for ch in ascii_only.lower())
    collapsed = "-".join(part for part in hyphenated.split("-") if part)
    return collapsed[:_MAX_SLUG_LENGTH].rstrip("-")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item and item.strip()))


def _build_location(raw: RawLocation | None, missing: list[str], questions: list[str]) -> Location | None:
    if raw is None or not (raw.city and raw.country):
        if raw and (raw.city or raw.country):
            missing.append("business_profile.location (city and a 2-letter country code are both needed)")
            questions.append("What city and country (ISO 2-letter code, e.g. ES, US) does the business operate in?")
        return None
    try:
        return Location(
            city=raw.city, region=raw.region, country=raw.country.strip().upper(), postal_code=raw.postal_code
        )
    except ValidationError:
        missing.append("business_profile.location.country (must be a 2-letter ISO country code)")
        questions.append(f"What is the 2-letter ISO country code for {raw.city}?")
        return None


def _build_contact(raw: RawContactInfo | None, missing: list[str], questions: list[str]) -> ContactInfo | None:
    if raw is None:
        return None

    def _reject(field: str, value: str, label: str) -> None:
        missing.append(f"business_profile.contact.{field} ({label}) — {value!r} did not validate")
        questions.append(f"Can you confirm the business's {label}?")

    email = raw.email
    if email:
        try:
            ContactInfo(email=email)
        except ValidationError:
            _reject("email", email, "email address")
            email = None

    phone = raw.phone
    if phone:
        try:
            ContactInfo(phone=phone)
        except ValidationError:
            _reject("phone", phone, "phone number")
            phone = None

    whatsapp = raw.whatsapp
    if whatsapp:
        try:
            ContactInfo(whatsapp=whatsapp)
        except ValidationError:
            _reject("whatsapp", whatsapp, "WhatsApp number")
            whatsapp = None

    website = raw.website.strip() if raw.website else None

    if not any([email, phone, whatsapp, website]):
        return None
    return ContactInfo(email=email, phone=phone, whatsapp=whatsapp, website=website)


def _build_services(raw_services: list[RawServiceOffering]) -> list[ServiceOffering]:
    services: list[ServiceOffering] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_services):
        # Reserve room for a "-N" disambiguation suffix so it never has to
        # be truncated back off (which could otherwise leave a trailing
        # hyphen SLUG_PATTERN rejects).
        base_id = slugify(item.name)[: _MAX_SLUG_LENGTH - 6].rstrip("-") or f"service-{index + 1}"
        service_id = base_id
        suffix = 2
        while service_id in seen_ids or not SLUG_PATTERN.match(service_id):
            service_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(service_id)
        services.append(
            ServiceOffering(
                id=service_id,
                name=item.name.strip()[:200],
                description=item.description.strip()[:2000],
                category=item.category.strip()[:100] if item.category else None,
            )
        )
    return services


def _build_lead_management(lead_sources: list[LeadSource]) -> LeadManagementConfig:
    if not lead_sources:
        return LeadManagementConfig()
    return LeadManagementConfig(enabled=True, sources=list(dict.fromkeys(lead_sources)))


def _build_automation(lead_capture: bool | None, lead_notifications: bool | None) -> AutomationConfig:
    config = AutomationConfig()
    updates: dict[str, bool] = {}
    if lead_capture is not None:
        updates["lead_capture"] = lead_capture
    if lead_notifications is not None:
        updates["lead_notifications"] = lead_notifications
    return config.model_copy(update=updates) if updates else config


def _incomplete(missing: list[str], questions: list[str]) -> BusinessAnalysisResult:
    return BusinessAnalysisResult(
        proposed_config=None, missing_information=_dedupe(missing), questions=_dedupe(questions)
    )


def assemble_result(raw: BusinessAnalysisOutput) -> BusinessAnalysisResult:
    missing = list(raw.missing_information)
    questions = list(raw.questions)

    name = (raw.business_name or "").strip()
    if not name:
        missing.append("business_profile.name (business name)")
        questions.append("What is the legal or trading name of the business?")
        return _incomplete(missing, questions)

    slug = slugify(name)
    if not slug:
        missing.append("business_profile.slug (could not derive a URL-safe slug from the business name)")
        questions.append("What short, URL-safe identifier (slug) should this business use?")
        return _incomplete(missing, questions)

    industry = raw.industry
    if industry is None:
        missing.append("business_profile.industry (business vertical)")
        questions.append("Which industry/vertical best describes this business?")
        industry = BusinessVertical.OTHER

    location = _build_location(raw.location, missing, questions)
    contact = _build_contact(raw.contact, missing, questions)
    services = _build_services(raw.services)

    description = (raw.description or "").strip()[:2000] or None
    target_customers = (raw.target_customers or "").strip()[:500] or None

    try:
        profile = BusinessProfile(
            name=name[:200],
            slug=slug,
            industry=industry,
            description=description,
            location=location,
            services=services,
            target_customers=target_customers,
            contact=contact,
        )
        config = BusinessConfig(
            business_profile=profile,
            lead_management=_build_lead_management(raw.lead_sources),
            automation=_build_automation(raw.automation_lead_capture, raw.automation_lead_notifications),
        )
    except ValidationError as exc:
        raise InvalidAnalysisOutputError(
            "The proposed business configuration failed final schema validation."
        ) from exc

    return BusinessAnalysisResult(
        proposed_config=config, missing_information=_dedupe(missing), questions=_dedupe(questions)
    )
