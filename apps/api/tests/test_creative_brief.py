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
    storage_provider: str | None = None
    storage_key: str | None = None
    unavailable_reason: str | None = None


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


def test_build_creative_brief_excludes_an_asset_with_a_confirmed_unavailable_reason():
    """Phase 6 hotfix (broken-asset detection): a BusinessAsset row whose
    real storage object has been confirmed missing (app.services.
    asset_health.check_business_asset_availability already ran and set
    this) must never reach a generated site or a Higgsfield reference —
    build_creative_brief is the single choke point every downstream
    consumer's asset list comes from, so filtering here is enough."""
    config = BusinessConfig(business_profile=_profile())
    healthy = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.GALLERY,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/healthy.jpg",
    )
    broken = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/broken-logo.jpg",
        unavailable_reason="Asset unavailable — please re-upload.",
    )

    brief = build_creative_brief(business_config=config, assets=[healthy, broken])

    urls = [asset.url for asset in brief.available_assets]
    assert "https://cdn.example.com/healthy.jpg" in urls
    assert "https://cdn.example.com/broken-logo.jpg" not in urls


def test_build_creative_brief_never_excludes_an_asset_that_was_simply_never_checked():
    """None means 'presumed fine, or not yet checked' — never treated as
    broken. Only a real, confirmed check (a non-None unavailable_reason)
    excludes an asset."""
    config = BusinessConfig(business_profile=_profile())
    never_checked = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.GALLERY,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/never-checked.jpg",
        unavailable_reason=None,
    )

    brief = build_creative_brief(business_config=config, assets=[never_checked])

    assert [asset.url for asset in brief.available_assets] == ["https://cdn.example.com/never-checked.jpg"]


def test_build_creative_brief_carries_storage_identity_through_for_healthy_assets():
    """Phase 5 (private provider references): a CreativeDirectorProvider
    needs storage_provider/storage_key on CreativeBriefAsset to know
    which assets it can mint a presigned URL for — see
    app.creative.higgsfield.director._resolve_reference_url."""
    config = BusinessConfig(business_profile=_profile())
    asset = _FakeAsset(
        id=uuid.uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.GALLERY,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://pub-abc123.r2.dev/biz-1/photo.jpg",
        storage_provider="r2",
        storage_key="biz-1/photo.jpg",
    )

    brief = build_creative_brief(business_config=config, assets=[asset])

    [brief_asset] = brief.available_assets
    assert brief_asset.storage_provider == "r2"
    assert brief_asset.storage_key == "biz-1/photo.jpg"
