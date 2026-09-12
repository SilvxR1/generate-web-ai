"""InternalCreativeProvider (app.creative.internal) and
HiggsfieldCreativeProvider (app.creative.higgsfield.provider): capability
declarations and behavior for each generation type — Section 21's
"InternalProvider compatibility" and "Higgsfield adapter boundary"."""

import pytest

from app.creative.errors import CreativeCapabilityNotSupportedError
from app.creative.higgsfield.client import HiggsfieldClient
from app.creative.higgsfield.provider import HiggsfieldCreativeProvider, HiggsfieldNotIntegratedError
from app.creative.internal import InternalCreativeProvider
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical, CreativeGenerationStatus, CreativeGenerationType, CreativeProviderName


def _brief():
    from app.domain.creative.brief import build_creative_brief

    config = BusinessConfig(
        business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER)
    )
    return build_creative_brief(business_config=config)


def test_internal_provider_declares_only_website_capabilities():
    provider = InternalCreativeProvider()

    assert provider.name is CreativeProviderName.INTERNAL
    assert provider.supports(CreativeGenerationType.WEBSITE)
    assert provider.supports(CreativeGenerationType.WEBSITE_CONCEPT)
    assert not provider.supports(CreativeGenerationType.IMAGE)
    assert not provider.supports(CreativeGenerationType.VIDEO)
    assert not provider.supports(CreativeGenerationType.VISUAL_ASSET)


def test_internal_provider_generate_website_completes_without_fabricating_content():
    provider = InternalCreativeProvider()

    result = provider.generate_website(_brief())

    assert result.status is CreativeGenerationStatus.COMPLETED
    assert result.assets == []
    assert result.credits_used is None
    assert result.estimated_cost is None


def test_internal_provider_generate_concept_completes():
    provider = InternalCreativeProvider()

    result = provider.generate_concept(_brief())

    assert result.status is CreativeGenerationStatus.COMPLETED


@pytest.mark.parametrize(
    "method_name",
    ["generate_image", "generate_video", "generate_visual_asset"],
)
def test_internal_provider_raises_for_unsupported_capabilities(method_name: str):
    provider = InternalCreativeProvider()
    method = getattr(provider, method_name)

    with pytest.raises(CreativeCapabilityNotSupportedError):
        method(_brief())


def _higgsfield_provider() -> HiggsfieldCreativeProvider:
    client = HiggsfieldClient(api_key="test-key", base_url="https://higgsfield.example.invalid")
    return HiggsfieldCreativeProvider(client)


def test_higgsfield_provider_declares_the_full_premium_capability_set():
    provider = _higgsfield_provider()

    assert provider.name is CreativeProviderName.HIGGSFIELD
    # Every CreativeGenerationType except CREATIVE_DIRECTION (P2): that
    # value tracks the separate CreativeDirectorProvider workflow
    # (app.creative.director — create_directions/develop_direction,
    # implemented by HiggsfieldCreativeDirector, a different class from
    # this CreativeProvider), not one of this ABC's five generate_*
    # capability methods, so it's deliberately not part of this set — see
    # app.domain.enums.CreativeGenerationType's own docstring.
    for generation_type in CreativeGenerationType:
        if generation_type is CreativeGenerationType.CREATIVE_DIRECTION:
            assert not provider.supports(generation_type)
            continue
        assert provider.supports(generation_type)


@pytest.mark.parametrize(
    "method_name",
    ["generate_concept", "generate_website", "generate_image", "generate_video", "generate_visual_asset"],
)
def test_higgsfield_provider_never_fakes_a_successful_call(method_name: str):
    """Section 10: 'Do NOT fake successful Higgsfield calls.' Every
    method must raise a clear, typed error — never return a
    CreativeGenerationResult with status=COMPLETED — since no real
    Higgsfield API contract is wired up in this codebase."""
    provider = _higgsfield_provider()
    method = getattr(provider, method_name)

    with pytest.raises(HiggsfieldNotIntegratedError) as exc_info:
        method(_brief())

    # The error must be specific enough to act on, not a generic failure.
    assert "Higgsfield" in str(exc_info.value)
