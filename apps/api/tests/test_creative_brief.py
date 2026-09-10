"""build_creative_brief / extract_customer_insights
(app.domain.creative.brief): deterministic assembly from a BusinessConfig
plus real assets/reviews — real-asset preference (Section 1), review
provenance (Section 4, "NEVER fabricate reviews"), and derived
required_sections/animation_level."""

import uuid
from dataclasses import dataclass

from app.domain.business_config import BrandColors, BrandConfig, BrandTypography, BusinessConfig, BusinessProfile
from app.domain.business_config.creative import CreativeConfig
from app.domain.creative.brief import build_creative_brief, extract_customer_insights
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BrandStrategy, BusinessVertical, CreativeLevel


def _profile(**overrides: object) -> BusinessProfile:
    data = {"name": "Reformas Valencia", "slug": "reformas-valencia", "industry": BusinessVertical.HOME_RENOVATION}
    data.update(overrides)
    return BusinessProfile(**data)


@dataclass
class _FakeAsset:
    id: uuid.UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    storage_url: str
    alt_text: str | None = None


@dataclass
class _FakeReview:
    body: str
    rating: int | None = None


def test_build_creative_brief_reads_business_identity_and_creative_intent():
    config = BusinessConfig(
        business_profile=_profile(description="Empresa familiar de reformas."),
        creative=CreativeConfig(strategy=BrandStrategy.PRESERVE, level=CreativeLevel.PROFESSIONAL),
    )

    brief = build_creative_brief(business_config=config)

    assert brief.business_name == "Reformas Valencia"
    assert brief.industry == "home_renovation"
    assert brief.description == "Empresa familiar de reformas."
    assert brief.brand_strategy is BrandStrategy.PRESERVE
    assert brief.creative_level is CreativeLevel.PROFESSIONAL
    assert brief.animation_level == "moderate"
    assert brief.required_pages == ["/"]


def test_build_creative_brief_includes_real_assets_with_their_origin_intact():
    """Section 1: 'REAL BUSINESS CONTENT > GENERATED CONTENT'. This
    doesn't mean generated assets are dropped — it means every asset
    carries its own real `origin` untouched, so a provider (or the
    orchestrator) can itself prefer real content without CreativeBrief
    ever blurring the two together."""
    config = BusinessConfig(business_profile=_profile())
    real_photo = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.PROJECT,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/real-project.jpg",
    )
    generated_photo = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.HERO_CANDIDATE,
        origin=AssetOrigin.GENERATED,
        storage_url="https://cdn.example.com/generated-hero.jpg",
    )

    brief = build_creative_brief(business_config=config, assets=[real_photo, generated_photo])

    origins_by_url = {asset.url: asset.origin for asset in brief.available_assets}
    assert origins_by_url["https://cdn.example.com/real-project.jpg"] is AssetOrigin.UPLOADED
    assert origins_by_url["https://cdn.example.com/generated-hero.jpg"] is AssetOrigin.GENERATED


def test_build_creative_brief_never_requests_a_hero_image_when_a_real_one_already_exists():
    config = BusinessConfig(
        business_profile=_profile(), creative=CreativeConfig(level=CreativeLevel.PREMIUM)
    )
    hero_candidate = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.HERO_CANDIDATE,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/hero.jpg",
    )

    brief = build_creative_brief(business_config=config, assets=[hero_candidate])

    assert "hero_image" not in brief.media_requirements


def test_build_creative_brief_requests_a_hero_image_when_none_exists_above_basic_level():
    config = BusinessConfig(
        business_profile=_profile(), creative=CreativeConfig(level=CreativeLevel.PREMIUM)
    )

    brief = build_creative_brief(business_config=config)

    assert "hero_image" in brief.media_requirements


def test_build_creative_brief_reads_brand_colors_and_typography_when_brand_configured():
    config = BusinessConfig(
        business_profile=_profile(),
        brand=BrandConfig(
            colors=BrandColors(
                primary="#b45309", secondary="#000", accent="#fff", background="#fff", foreground="#000"
            ),
            typography=BrandTypography(sans="Inter"),
        ),
    )

    brief = build_creative_brief(business_config=config)

    assert brief.brand_colors is not None and brief.brand_colors.primary == "#b45309"
    assert brief.typography is not None and brief.typography.sans == "Inter"


def test_build_creative_brief_never_fabricates_differentiators():
    """Section 6 lists 'differentiators' as future Business Analyzer
    output — nothing in this codebase derives them from real data yet,
    so build_creative_brief must never invent any."""
    config = BusinessConfig(business_profile=_profile())

    brief = build_creative_brief(business_config=config)

    assert brief.differentiators == []


def test_extract_customer_insights_only_surfaces_labels_backed_by_real_review_text():
    reviews = [
        _FakeReview(body="Very clean while working."),
        _FakeReview(body="Finished exactly on schedule."),
        _FakeReview(body="The quote didn't change."),
        _FakeReview(body="Pedro kept us informed throughout."),
    ]

    insights = extract_customer_insights(reviews)

    assert "cleanliness" in insights
    assert "reliability" in insights
    assert "transparent_pricing" in insights
    assert "communication" in insights
    # Never invented: no review here mentions friendliness or value.
    assert "friendliness" not in insights
    assert "value_for_money" not in insights


def test_extract_customer_insights_is_empty_with_no_reviews():
    assert extract_customer_insights([]) == []


def test_build_creative_brief_never_carries_the_reviews_themselves():
    """CreativeBrief exposes insights, never a review dossier — the raw
    review text (which could include a customer's name or other
    identifying detail) must not leak into what's sent to a creative
    provider."""
    config = BusinessConfig(business_profile=_profile())
    reviews = [_FakeReview(body="Pedro kept us informed throughout, very clean and reliable team.")]

    brief = build_creative_brief(business_config=config, reviews=reviews)

    assert not hasattr(brief, "reviews")
    assert "Pedro" not in str(brief.model_dump())


def test_build_creative_brief_adds_testimonials_section_only_when_reviews_exist():
    config = BusinessConfig(business_profile=_profile())

    without_reviews = build_creative_brief(business_config=config)
    with_reviews = build_creative_brief(business_config=config, reviews=[_FakeReview(body="Great work.")])

    assert "testimonials" not in without_reviews.required_sections
    assert "testimonials" in with_reviews.required_sections
