"""BusinessTruth (v0.2 R1) — what the platform actually knows about a
business, and the ONLY factual source material a generated website may use.

    BusinessTruth defines what the platform knows.
    It does not define how the website should look.

Deterministic: `derive_business_truth` is a pure function of stored platform
data (the owner-reviewed BusinessConfig, the business's BusinessAsset rows,
its BusinessReview rows). No AI, no provider, no I/O — the same stored state
always yields the same BusinessTruth and the same `canonical_json()`.

Provider-independent: nothing here knows about Anthropic, Higgsfield, Astro,
SiteConfig, Studio or Cloudflare; any builder can consume it.

Never contains presentation (layout, sections, typography, colors, spacing,
hero/gallery choices) — those belong to creative direction/generation — and
never contains secrets or private storage identifiers (only an asset's
public URL, which is already what a published site embeds).

Generated presentation is not automatically promoted into BusinessTruth:
text or images that appear on a generated website never flow back into it.
GENERATED assets are listed with their provenance and are never treated as
real business assets (never the logo, never a "real photo").

Source hierarchy (see docs/v0.2-generative-website-architecture.md, R1):
- identity/description/services/contact/location/hours/legal/WhatsApp:
  BusinessConfig — produced from the owner's briefing by the Business
  Analyzer and reviewed/edited by a human before it is saved
  (OWNER_REVIEWED).
- assets: BusinessAsset rows — `origin` is the provenance
  (UPLOADED/IMPORTED = real, GENERATED = generated).
- logo: a real (uploaded/imported) logo asset; else the owner-entered
  `brand.logo`; else absent. Never a generated asset, never a text wordmark.
- reviews: visible BusinessReview rows only, with their source; never
  synthesized.
- claims: no structured claims model exists; see ClaimsTruth.

This is WHAT IS TRUE. Whether generated output stayed within it is the
future Truth Contract's job (not implemented here).
"""

import json
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config import BusinessConfig
from app.domain.business_config.business_profile import PostalAddress
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, ReviewSource, Weekday

BUSINESS_TRUTH_VERSION = "1"


class FactSource(StrEnum):
    """Where a section's facts come from. Deliberately small: the existing
    AssetOrigin (assets) and ReviewSource (reviews) carry item-level
    provenance; this labels the sections that come from BusinessConfig."""

    OWNER_REVIEWED = "owner_reviewed"  # BusinessConfig: analyzer-proposed, human-reviewed, saved
    OWNER_PROVIDED = "owner_provided"  # entered/uploaded by the owner or operator directly
    EXTERNAL_IMPORTED = "external_imported"  # imported from an external provider (e.g. Google reviews)
    GENERATED = "generated"  # produced by a creative provider — never an authoritative fact
    DERIVED = "derived"  # deterministically computed from the above


class _Truth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IdentityTruth(_Truth):
    name: str
    slug: str
    industry: str
    tagline: str | None = None  # owner-provided copy; may contain unverified assertions (see ClaimsTruth)


class DescriptionTruth(_Truth):
    description: str | None = None
    target_customers: str | None = None


class ServiceTruth(_Truth):
    id: str
    name: str
    description: str
    short_description: str | None = None
    category: str | None = None
    price_from: float | None = None
    price_unit: str | None = None


class AddressTruth(_Truth):
    street_address: str
    locality: str
    region: str | None = None
    postal_code: str | None = None
    country: str

    @classmethod
    def from_postal(cls, address: PostalAddress | None) -> "AddressTruth | None":
        if address is None:
            return None
        return cls(
            street_address=address.street_address,
            locality=address.locality,
            region=address.region,
            postal_code=address.postal_code,
            country=address.country,
        )


class WhatsAppTruth(_Truth):
    """Present only when the owner explicitly enabled the WhatsApp channel
    AND gave its number (BusinessConfig.whatsapp) — never inferred from a
    phone number."""

    phone_number: str
    default_message: str | None = None


class ContactTruth(_Truth):
    email: str | None = None
    phone: str | None = None
    # An owner-entered WhatsApp contact detail (BusinessConfig contact.whatsapp)
    # — a listed contact value, distinct from the WhatsApp CTA channel above.
    whatsapp_contact: str | None = None
    website: str | None = None
    address: AddressTruth | None = None
    whatsapp: WhatsAppTruth | None = None


class LocationTruth(_Truth):
    city: str | None = None
    region: str | None = None
    country: str | None = None
    postal_code: str | None = None
    service_area: list[str] = Field(default_factory=list)


class OpeningHoursTruth(_Truth):
    days: list[Weekday]
    opens: str
    closes: str


class LegalTruth(_Truth):
    """Only what the owner actually recorded; every missing field is None —
    never guessed, never substituted with the trading name."""

    legal_name: str | None = None
    registration_number: str | None = None
    tax_id: str | None = None
    registered_address: AddressTruth | None = None
    privacy_contact_email: str | None = None
    data_processors: list[str] = Field(default_factory=list)


class AssetTruth(_Truth):
    id: UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    is_real: bool  # uploaded/imported by the business — never a generated image
    url: str  # the public, renderable URL (what a published site embeds); no storage keys
    alt_text: str | None = None


class LogoTruth(_Truth):
    source: FactSource  # OWNER_PROVIDED (real asset or owner-entered brand.logo)
    url: str
    alt_text: str | None = None
    asset_id: UUID | None = None  # set when the logo is a real BusinessAsset


class ReviewTruth(_Truth):
    id: UUID
    source: ReviewSource
    provenance: FactSource  # EXTERNAL_IMPORTED (provider) or OWNER_PROVIDED (manual)
    source_review_id: str | None = None
    author_name: str | None = None  # only if actually supplied
    rating: int | None = None  # only if actually supplied
    body: str
    review_url: str | None = None
    published_at: datetime | None = None


class ClaimsTruth(_Truth):
    """No structured claims model exists in the platform yet. `supported`
    is therefore always empty: there is no stored statistic, certification,
    award, "years of experience" or project count a website may state.
    `unverified_free_text_fields` names the owner-written prose fields that
    MAY contain such assertions (reproduced faithfully, never extended or
    quantified)."""

    supported: list[str] = Field(default_factory=list)
    unverified_free_text_fields: list[str] = Field(
        default_factory=lambda: ["identity.tagline", "description.description", "services[].description"]
    )


class BusinessTruth(_Truth):
    version: str = BUSINESS_TRUTH_VERSION
    identity: IdentityTruth
    description: DescriptionTruth
    services: list[ServiceTruth]
    contact: ContactTruth
    location: LocationTruth
    opening_hours: list[OpeningHoursTruth]
    legal: LegalTruth
    logo: LogoTruth | None  # None = the business has no real logo
    assets: list[AssetTruth]
    reviews: list[ReviewTruth]  # empty = no reviews (never "generate testimonials")
    claims: ClaimsTruth
    provenance: dict[str, FactSource]

    @property
    def real_assets(self) -> list[AssetTruth]:
        return [asset for asset in self.assets if asset.is_real]

    def canonical_json(self) -> str:
        """Stable serialization for prompts, tests and the future Truth
        Contract: identical state → identical string."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2)


# --- Inputs (structural, like app.domain.creative.brief's Protocols) -------


class TruthAssetInput(Protocol):
    """CreativeBriefAsset (already filtered to available assets) satisfies this."""

    id: UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    url: str
    alt_text: str | None


class TruthReviewInput(Protocol):
    """app.db.models.business_review.BusinessReview satisfies this."""

    id: UUID
    source: ReviewSource
    source_review_id: str | None
    author_name: str | None
    rating: int | None
    body: str
    review_url: str | None
    published_at: datetime | None
    is_visible: bool


_REAL_ORIGINS = frozenset({AssetOrigin.UPLOADED, AssetOrigin.IMPORTED})


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _asset_sort_key(asset: TruthAssetInput) -> tuple:
    return (0 if asset.origin in _REAL_ORIGINS else 1, asset.category.value, asset.kind.value, str(asset.id))


def _logo(business_config: BusinessConfig, assets: Sequence[TruthAssetInput]) -> LogoTruth | None:
    real_logos = sorted(
        (
            asset
            for asset in assets
            if asset.origin in _REAL_ORIGINS
            and (asset.kind is AssetKind.LOGO or asset.category is AssetCategory.LOGO)
            and asset.category is not AssetCategory.LOW_QUALITY
        ),
        key=_asset_sort_key,
    )
    if real_logos:
        logo = real_logos[0]
        return LogoTruth(
            source=FactSource.OWNER_PROVIDED, url=logo.url, alt_text=_strip(logo.alt_text), asset_id=logo.id
        )
    brand = business_config.brand
    if brand is not None and brand.logo is not None:
        return LogoTruth(source=FactSource.OWNER_PROVIDED, url=brand.logo.url, alt_text=_strip(brand.logo.alt))
    return None


def _review_sort_key(review: TruthReviewInput) -> tuple:
    published = review.published_at.isoformat() if review.published_at else ""
    return (published, str(review.id))


def _review(review: TruthReviewInput) -> ReviewTruth:
    rating = review.rating if review.rating is not None and 1 <= review.rating <= 5 else None
    return ReviewTruth(
        id=review.id,
        source=review.source,
        provenance=FactSource.OWNER_PROVIDED if review.source is ReviewSource.MANUAL else FactSource.EXTERNAL_IMPORTED,
        source_review_id=_strip(review.source_review_id),
        author_name=_strip(review.author_name),
        rating=rating,
        body=review.body.strip(),
        review_url=_strip(review.review_url),
        published_at=review.published_at,
    )


def derive_business_truth(
    *,
    business_config: BusinessConfig,
    assets: Sequence[TruthAssetInput] = (),
    reviews: Sequence[TruthReviewInput] = (),
) -> BusinessTruth:
    """Pure and deterministic. `assets` should be the business's available
    assets (e.g. CreativeBrief.available_assets); `reviews` its stored
    BusinessReview rows (hidden ones are dropped here)."""
    profile = business_config.business_profile
    contact = profile.contact
    whatsapp_config = business_config.whatsapp
    legal = business_config.legal_profile
    location = profile.location

    whatsapp = (
        WhatsAppTruth(
            phone_number=whatsapp_config.phone_number,
            default_message=_strip(whatsapp_config.default_message),
        )
        if whatsapp_config.enabled and whatsapp_config.phone_number
        else None
    )

    return BusinessTruth(
        identity=IdentityTruth(
            name=profile.name,
            slug=profile.slug,
            industry=profile.industry.value,
            tagline=_strip(business_config.brand.tagline) if business_config.brand else None,
        ),
        description=DescriptionTruth(
            description=_strip(profile.description), target_customers=_strip(profile.target_customers)
        ),
        services=[
            ServiceTruth(
                id=service.id,
                name=service.name,
                description=service.description,
                short_description=_strip(service.short_description),
                category=_strip(service.category),
                price_from=service.price_from,
                price_unit=_strip(service.price_unit),
            )
            for service in profile.services  # owner order is meaningful and stable
        ],
        contact=ContactTruth(
            email=str(contact.email) if contact and contact.email else None,
            phone=_strip(contact.phone) if contact else None,
            whatsapp_contact=_strip(contact.whatsapp) if contact else None,
            website=_strip(contact.website) if contact else None,
            address=AddressTruth.from_postal(contact.address) if contact else None,
            whatsapp=whatsapp,
        ),
        location=LocationTruth(
            city=location.city if location else None,
            region=location.region if location else None,
            country=location.country if location else None,
            postal_code=location.postal_code if location else None,
            service_area=list(profile.service_area),
        ),
        opening_hours=[
            OpeningHoursTruth(days=list(rule.days), opens=rule.opens, closes=rule.closes)
            for rule in profile.business_hours
        ],
        legal=LegalTruth(
            legal_name=_strip(legal.legal_name) if legal else None,
            registration_number=_strip(legal.registration_number) if legal else None,
            tax_id=_strip(legal.tax_id) if legal else None,
            registered_address=AddressTruth.from_postal(legal.address) if legal else None,
            privacy_contact_email=str(legal.privacy_contact_email) if legal and legal.privacy_contact_email else None,
            data_processors=list(legal.data_processors) if legal else [],
        ),
        logo=_logo(business_config, assets),
        assets=[
            AssetTruth(
                id=asset.id,
                kind=asset.kind,
                category=asset.category,
                origin=asset.origin,
                is_real=asset.origin in _REAL_ORIGINS,
                url=asset.url,
                alt_text=_strip(asset.alt_text),
            )
            for asset in sorted(assets, key=_asset_sort_key)
        ],
        reviews=[_review(review) for review in sorted(reviews, key=_review_sort_key) if review.is_visible],
        claims=ClaimsTruth(),
        provenance={
            "identity": FactSource.OWNER_REVIEWED,
            "description": FactSource.OWNER_REVIEWED,
            "services": FactSource.OWNER_REVIEWED,
            "contact": FactSource.OWNER_REVIEWED,
            "location": FactSource.OWNER_REVIEWED,
            "opening_hours": FactSource.OWNER_REVIEWED,
            "legal": FactSource.OWNER_REVIEWED,
            "logo": FactSource.OWNER_PROVIDED,
            "assets": FactSource.DERIVED,  # per-asset provenance is `origin`
            "reviews": FactSource.DERIVED,  # per-review provenance is `provenance`
        },
    )
