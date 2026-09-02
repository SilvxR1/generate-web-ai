"""BusinessProfile and its parts (location, contact, services, hours).

Pure domain data: no FastAPI, no SQLAlchemy, no provider SDKs. Consumed
by app.schemas.business (the API layer) and, eventually, by whatever
turns an AI Business Analyzer's structured output into this shape.
"""

import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.enums import BusinessVertical, Weekday

# Reused by both BusinessProfile.slug here and Business.slug in
# app.schemas.business (the top-level, DB-unique column) — one pattern,
# not two independently-maintained regexes for "what is a valid slug."
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_PHONE_PATTERN = re.compile(r"^\+?[0-9()\-.\s]{6,20}$")


def _validate_phone_like(value: str) -> str:
    stripped = value.strip()
    if not _PHONE_PATTERN.match(stripped):
        raise ValueError(f"{value!r} does not look like a phone/WhatsApp number.")
    return stripped


class Location(BaseModel):
    """Coarse operating location for service-area context — not
    necessarily a full mailing address (see ContactInfo.address for
    that). Deliberately shallow per Section 3's instruction not to
    over-model geography."""

    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    # ISO 3166-1 alpha-2, matching packages/site-config's
    # LocalBusinessAddress.addressCountry convention.
    country: str = Field(min_length=2, max_length=2)
    postal_code: str | None = Field(default=None, max_length=20)


class PostalAddress(BaseModel):
    """Mirrors packages/site-config's LocalBusinessAddress field-for-field
    (streetAddress/addressLocality/addressRegion/postalCode/
    addressCountry) so this data stays compatible with that package's
    schema.org LocalBusiness JSON-LD shape if a future website generator
    needs to emit it from BusinessConfig instead of hand-authored config.
    """

    model_config = ConfigDict(extra="forbid")

    street_address: str = Field(min_length=1, max_length=200)
    locality: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(min_length=2, max_length=2)


class ContactInfo(BaseModel):
    """How customers reach the business. Every field optional — Section 4
    warns against restrictions that would make real businesses (e.g. one
    with only a phone, no email) unrepresentable."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    phone: str | None = None
    whatsapp: str | None = None
    website: str | None = Field(default=None, max_length=2048)
    address: PostalAddress | None = None

    @field_validator("phone", "whatsapp")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _validate_phone_like(value) if value else value


class BusinessHoursRule(BaseModel):
    """One opening-hours rule: a set of days sharing the same opening and
    closing time. Mirrors packages/site-config's
    LocalBusinessOpeningHours shape, but `days` is a controlled
    vocabulary (Weekday) rather than free-text — this layer isn't
    trusted hand-authored content the way that one is."""

    model_config = ConfigDict(extra="forbid")

    days: list[Weekday] = Field(min_length=1)
    opens: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    closes: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ServiceOffering(BaseModel):
    """A service the business offers, at the business-catalog level —
    price/category, not rendering props. Deliberately NOT the same type
    as packages/site-config's ServiceItemConfig (icon/image/action/
    featured, meant for a Services block's rendering), which sits one
    abstraction level lower: that's what a website generator would
    eventually produce FROM a ServiceOffering, not a shape this layer
    should hold directly."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    short_description: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    price_from: float | None = Field(default=None, ge=0)
    price_unit: str | None = Field(default=None, max_length=50)
    featured: bool = False


class BusinessProfile(BaseModel):
    """The core "who is this business" facts. Only name/slug/industry are
    required — everything else can be filled in incrementally (Section 3:
    not every field has to be mandatory)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    industry: BusinessVertical
    description: str | None = Field(default=None, max_length=2000)
    location: Location | None = None
    service_area: list[str] = Field(default_factory=list)
    services: list[ServiceOffering] = Field(default_factory=list)
    target_customers: str | None = Field(default=None, max_length=500)
    contact: ContactInfo | None = None
    business_hours: list[BusinessHoursRule] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped
