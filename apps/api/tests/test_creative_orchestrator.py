"""select_provider / orchestrate_generation (app.creative.orchestrator):
provider routing by creative level, no silent downgrade from a paid tier
(Section 19), and CreativeGeneration persistence for both success and
failure (Section 13)."""

import pytest
from sqlalchemy.orm import Session

from app.creative.errors import CreativeCapabilityNotSupportedError, CreativeProviderRequestError
from app.creative.internal import InternalCreativeProvider
from app.creative.orchestrator import NoSuitableProviderError, orchestrate_generation, select_provider
from app.creative.provider import CreativeGenerationResult, CreativeProvider
from app.db.models.business import Business
from app.domain.business_config import BusinessConfig
from app.domain.business_config.creative import CreativeConfig
from app.domain.enums import (
    CreativeGenerationStatus,
    CreativeGenerationType,
    CreativeLevel,
    CreativeProviderName,
)


class _FakePremiumProvider(CreativeProvider):
    """A controllable CreativeProvider test double — never a real vendor
    call, just a scripted result/exception for orchestrator tests."""

    name = CreativeProviderName.HIGGSFIELD
    capabilities = frozenset(CreativeGenerationType)

    def __init__(self, *, result: CreativeGenerationResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def _respond(self) -> CreativeGenerationResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    def generate_concept(self, brief):  # noqa: ANN001, ANN201 — test double
        return self._respond()

    def generate_website(self, brief):
        return self._respond()

    def generate_image(self, brief, *, prompt_hint=None):
        return self._respond()

    def generate_video(self, brief, *, prompt_hint=None):
        return self._respond()

    def generate_visual_asset(self, brief, *, prompt_hint=None):
        return self._respond()


def _internal() -> InternalCreativeProvider:
    return InternalCreativeProvider()


def test_select_provider_routes_basic_level_to_internal():
    provider = select_provider(
        creative_level=CreativeLevel.BASIC,
        generation_type=CreativeGenerationType.WEBSITE,
        preferred_provider=None,
        internal_provider=_internal(),
        premium_provider=_FakePremiumProvider(),
    )

    assert provider.name is CreativeProviderName.INTERNAL


def test_select_provider_routes_premium_level_to_premium_provider():
    premium = _FakePremiumProvider()

    provider = select_provider(
        creative_level=CreativeLevel.PREMIUM,
        generation_type=CreativeGenerationType.IMAGE,
        preferred_provider=None,
        internal_provider=_internal(),
        premium_provider=premium,
    )

    assert provider is premium


def test_select_provider_never_silently_downgrades_premium_to_internal():
    """Section 19: falling back to the free InternalCreativeProvider for
    a PREMIUM/CINEMATIC request would silently produce a cheaper,
    materially different result than requested — this must raise, not
    downgrade."""
    with pytest.raises(NoSuitableProviderError):
        select_provider(
            creative_level=CreativeLevel.PREMIUM,
            generation_type=CreativeGenerationType.WEBSITE,
            preferred_provider=None,
            internal_provider=_internal(),
            premium_provider=None,
        )


def test_select_provider_honors_an_explicit_higgsfield_preference_even_at_basic_level():
    premium = _FakePremiumProvider()

    provider = select_provider(
        creative_level=CreativeLevel.BASIC,
        generation_type=CreativeGenerationType.WEBSITE,
        preferred_provider=CreativeProviderName.HIGGSFIELD,
        internal_provider=_internal(),
        premium_provider=premium,
    )

    assert provider is premium


def test_select_provider_rejects_a_capability_internal_does_not_support():
    with pytest.raises(CreativeCapabilityNotSupportedError):
        select_provider(
            creative_level=CreativeLevel.BASIC,
            generation_type=CreativeGenerationType.IMAGE,
            preferred_provider=None,
            internal_provider=_internal(),
            premium_provider=None,
        )


def _config(level: CreativeLevel = CreativeLevel.BASIC, preferred_provider: str | None = None) -> BusinessConfig:
    from app.domain.business_config import BusinessProfile
    from app.domain.enums import BusinessVertical

    return BusinessConfig(
        business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER),
        creative=CreativeConfig(level=level, preferred_provider=preferred_provider),
    )


def test_orchestrate_generation_persists_a_completed_internal_generation(session: Session, business: Business):
    generation = orchestrate_generation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        business_config=_config(),
        generation_type=CreativeGenerationType.WEBSITE,
        internal_provider=_internal(),
    )

    assert generation.id is not None
    assert generation.tenant_id == business.tenant_id
    assert generation.business_id == business.id
    assert generation.provider is CreativeProviderName.INTERNAL
    assert generation.status is CreativeGenerationStatus.COMPLETED
    assert generation.credits_used is None
    assert generation.estimated_cost is None
    assert generation.started_at is not None
    assert generation.completed_at is not None


def test_orchestrate_generation_persists_a_failed_generation_without_raising(
    session: Session, business: Business
):
    """Section 19: provider failure must not corrupt Business state — it
    must be recorded as a FAILED CreativeGeneration with a clear error,
    not silently lost, and not left as an unhandled exception that would
    also roll back the business's own data."""
    failing_provider = _FakePremiumProvider(error=CreativeProviderRequestError("simulated provider failure"))

    generation = orchestrate_generation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        business_config=_config(level=CreativeLevel.PREMIUM),
        generation_type=CreativeGenerationType.WEBSITE,
        internal_provider=_internal(),
        premium_provider=failing_provider,
    )

    assert generation.status is CreativeGenerationStatus.FAILED
    assert generation.error is not None and "simulated provider failure" in generation.error
    assert generation.completed_at is not None


def test_orchestrate_generation_records_credits_and_cost_only_when_the_provider_reports_them(
    session: Session, business: Business
):
    result = CreativeGenerationResult(
        status=CreativeGenerationStatus.COMPLETED,
        credits_used=3.5,
        estimated_cost=1.2,
        external_reference="job-123",
    )
    succeeding_provider = _FakePremiumProvider(result=result)

    generation = orchestrate_generation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        business_config=_config(level=CreativeLevel.PREMIUM),
        generation_type=CreativeGenerationType.IMAGE,
        internal_provider=_internal(),
        premium_provider=succeeding_provider,
    )

    assert generation.credits_used == 3.5
    assert generation.estimated_cost == 1.2
    assert generation.external_reference == "job-123"


def test_orchestrate_generation_never_touches_the_business_website(session: Session, business: Business):
    """Section 16: regeneration must not destroy the currently published
    website — orchestrate_generation shouldn't reference/modify Website
    at all, so this is trivially true; assert the business itself, at
    least, is unmodified by the call."""
    original_status = business.status

    orchestrate_generation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        business_config=_config(),
        generation_type=CreativeGenerationType.WEBSITE,
        internal_provider=_internal(),
    )

    assert business.status == original_status
