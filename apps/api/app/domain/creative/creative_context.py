"""CreativeContext (P2.4) — the ONLY business knowledge an image model is
allowed to see, filtered from the broader CreativeBrief.

Why: Experiment 3 sent a `description` full of operational/digital context
("Instagram", "sin página web", "ecommerce", "catálogo … contacto") plus an
`ecommerce` industry label and a "website hero" placement to a text-to-image
model with no reference. The model drew what the words described: a website
mockup. Business knowledge for imagery must be *visual*, verified and
short — not the whole profile.

Design (conservative by construction):

- STRUCTURED FIELDS ONLY. Free-text prose (`description`, `target_customers`,
  tagline, service descriptions, reviews) is never forwarded: it can carry
  operational context, and no heuristic can reliably understand arbitrary
  prose. If uncertain, exclude. A future extractor for useful facts that only
  exist in prose would plug in behind this boundary with its own provenance.
- The industry label is used only when it names something visual
  (`restaurant`, `hotel`, ...). `ecommerce`, `agency`, `b2b_services` and
  `other` describe a business *model* or nothing at all — they stay unknown.
- Service names are short structured labels; each is kept only if it passes
  a conservative filter (no contact/URL/handle patterns, no operational or
  digital terms, no business name, short). Being a real service does not make
  it a photographic subject; the filter can only remove, never invent.
- Missing information stays UNKNOWN. Nothing here turns absence into a
  specific subject, venue or product.
- Decisions are recorded as field names and reason codes — never raw text — so
  provenance can explain the context without duplicating business data.

The term filter below is applied only to short service *labels*, as a
removal step. It is not a substitution pass over prose and does not claim to
understand language.
"""

import re
import unicodedata
from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brief import CreativeBrief

CREATIVE_CONTEXT_VERSION = "p2.4-v1"

_MAX_SUBJECTS = 4
_MAX_LABEL_CHARS = 60
_MAX_LABEL_WORDS = 8

# Verticals that name something with a physical/visual presence. Everything
# else (ecommerce, agency, b2b_services, other) is unknown, not guessed.
_VISUAL_CATEGORY: dict[str, str] = {
    "home_renovation": "home renovation",
    "real_estate": "real estate",
    "clinic": "healthcare clinic",
    "restaurant": "restaurant",
    "hotel": "hotel",
}

_OPERATIONAL_TERMS: tuple[str, ...] = (
    "web",
    "website",
    "webpage",
    "sitio web",
    "pagina web",
    "seo",
    "sem",
    "marketing",
    "redes sociales",
    "social media",
    "instagram",
    "facebook",
    "tiktok",
    "twitter",
    "linkedin",
    "youtube",
    "whatsapp",
    "telegram",
    "ecommerce",
    "e-commerce",
    "tienda online",
    "online store",
    "hosting",
    "dominio",
    "domain",
    "crm",
    "software",
    "app",
    "aplicacion",
    "email",
    "correo",
    "newsletter",
    "booking",
    "reserva online",
    "analytics",
    "pago",
    "payment",
    "stripe",
    "paypal",
    "api",
    "integracion",
    "integration",
    "automatizacion",
    "automation",
    "digital",
)

_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|es|net|org|io|app)\b", re.IGNORECASE)
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_HANDLE = re.compile(r"(^|\s)@\w+")


class ExcludedReason(StrEnum):
    FREE_TEXT_NOT_FORWARDED = "free_text_may_carry_operational_or_digital_context"
    NOT_A_VISUAL_SUBJECT = "not_a_visual_subject"
    OPERATIONAL_OR_DIGITAL_TERM = "operational_or_digital_term"
    CONTACT_OR_HANDLE_PATTERN = "contact_or_handle_pattern"
    NOT_A_SHORT_LABEL = "not_a_short_label"
    BUSINESS_NAME_NOT_FOR_IMAGES = "business_name_is_rendered_by_the_website_not_the_image"
    NOT_USED_FOR_IMAGERY = "not_used_for_imagery"
    OPERATIONAL_CONFIGURATION = "operational_website_configuration"
    OVER_LIMIT = "over_limit"


class ExcludedContext(BaseModel):
    """What was left out and why — never the excluded text itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    reason: ExcludedReason
    count: int = 1


class CreativeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = CREATIVE_CONTEXT_VERSION
    # A visual-domain phrase ("restaurant"), or None when the business type
    # says nothing about what to depict.
    business_category: str | None = None
    # Verified offering names that passed the filter. Category-level labels,
    # not depictions of specific real products.
    subject_categories: list[str] = Field(default_factory=list)
    included_fields: list[str] = Field(default_factory=list)
    excluded: list[ExcludedContext] = Field(default_factory=list)
    # Things the image model has no verified information about.
    unknown: list[str] = Field(default_factory=list)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _label_exclusion(label: str, business_name: str) -> ExcludedReason | None:
    if len(label) > _MAX_LABEL_CHARS or len(label.split()) > _MAX_LABEL_WORDS:
        return ExcludedReason.NOT_A_SHORT_LABEL
    if _EMAIL.search(label) or _URL.search(label) or _PHONE.search(label) or _HANDLE.search(label):
        return ExcludedReason.CONTACT_OR_HANDLE_PATTERN
    normalized = _normalize(label)
    if business_name.strip() and _normalize(business_name) in normalized:
        return ExcludedReason.BUSINESS_NAME_NOT_FOR_IMAGES
    for term in _OPERATIONAL_TERMS:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized):
            return ExcludedReason.OPERATIONAL_OR_DIGITAL_TERM
    return None


def build_creative_context(brief: CreativeBrief) -> CreativeContext:
    """Deterministic, pure, structured-fields-only."""
    included: list[str] = []
    excluded: list[ExcludedContext] = [
        ExcludedContext(field="business_name", reason=ExcludedReason.BUSINESS_NAME_NOT_FOR_IMAGES)
    ]
    unknown: list[str] = []

    category = _VISUAL_CATEGORY.get(brief.industry)
    if category:
        included.append("industry")
    else:
        excluded.append(ExcludedContext(field="industry", reason=ExcludedReason.NOT_A_VISUAL_SUBJECT))
        unknown.append("business_category")

    subjects: list[str] = []
    rejected: Counter[ExcludedReason] = Counter()
    seen: set[str] = set()
    for service in brief.services:
        label = " ".join(service.name.split())
        reason = _label_exclusion(label, brief.business_name)
        if reason is None and label.lower() in seen:
            continue
        if reason is None and len(subjects) >= _MAX_SUBJECTS:
            reason = ExcludedReason.OVER_LIMIT
        if reason is not None:
            rejected[reason] += 1
            continue
        seen.add(label.lower())
        subjects.append(label)
    if subjects:
        included.append("services")
    else:
        unknown.append("subject_categories")
    excluded.extend(ExcludedContext(field="services", reason=reason, count=count) for reason, count in rejected.items())

    prose_fields = (
        ("description", brief.description),
        ("target_customers", brief.target_customer),
        ("service_descriptions", any(service.description for service in brief.services)),
    )
    excluded.extend(
        ExcludedContext(field=name, reason=ExcludedReason.FREE_TEXT_NOT_FORWARDED)
        for name, present in prose_fields
        if present
    )
    unused_fields = (
        ("tagline", brief.tagline),
        ("location", brief.location),
        ("customer_insights", brief.customer_insights),
    )
    excluded.extend(
        ExcludedContext(field=name, reason=ExcludedReason.NOT_USED_FOR_IMAGERY)
        for name, present in unused_fields
        if present
    )
    excluded.append(ExcludedContext(field="website_configuration", reason=ExcludedReason.OPERATIONAL_CONFIGURATION))

    return CreativeContext(
        business_category=category,
        subject_categories=subjects,
        included_fields=included,
        excluded=excluded,
        unknown=unknown,
    )
