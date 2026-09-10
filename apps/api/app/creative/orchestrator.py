"""CreativeOrchestrator — decides how a creative generation request is
executed, per Section 11 of the master context: Business -> analyze ->
build CreativeBrief -> choose provider -> generate -> normalize -> persist
-> prepare for QA/deployment.

Contains no vendor-specific logic (no Higgsfield/Anthropic/Cloudflare
awareness anywhere in this module) — that belongs inside each
CreativeProvider implementation, never here. Never touches a business's
live Website row: applying a generation's output to the published site
stays the existing, separate, explicit publish action
(app.publishing.service.publish_website) — Section 19's "provider failure
must not corrupt Business state" and Section 16's "regeneration must not
destroy the currently published website" both hold by construction here,
not because of extra logic in this module.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.creative.errors import CreativeCapabilityNotSupportedError, CreativeProviderError
from app.creative.provider import CreativeGenerationResult, CreativeProvider
from app.db.models.creative_generation import CreativeGeneration
from app.domain.business_config import BusinessConfig
from app.domain.creative import AssetInput, ReviewInput, build_creative_brief
from app.domain.creative.brief import CreativeBrief
from app.domain.enums import CreativeGenerationStatus, CreativeGenerationType, CreativeLevel, CreativeProviderName
from app.repositories.creative_generation import CreativeGenerationRepository


class NoSuitableProviderError(CreativeProviderError):
    """Raised by select_provider when the requested CreativeLevel calls
    for a premium provider (PREMIUM/CINEMATIC) and none is configured —
    Section 19's "do not silently fallback if that would unexpectedly
    create billable/meaningfully different output": falling back to the
    free InternalCreativeProvider here would silently produce a cheaper,
    materially different result than what was requested, so this raises
    instead of downgrading."""


# BASIC/PROFESSIONAL are satisfied by the free internal pipeline by
# design, not as a fallback — Section 12 describes BASIC as "primarily
# internal generation" and PROFESSIONAL as premium *design* generation
# "and potentially generated supporting imagery" (i.e. still routable
# through Internal today, since no image generation exists on either
# provider path except Higgsfield once integrated). PREMIUM/CINEMATIC
# ("advanced design generation", "high-end visual generation") require a
# premium provider — if none is configured, select_provider raises rather
# than quietly using Internal instead.
_LEVELS_REQUIRING_PREMIUM_PROVIDER = frozenset({CreativeLevel.PREMIUM, CreativeLevel.CINEMATIC})


def select_provider(
    *,
    creative_level: CreativeLevel,
    generation_type: CreativeGenerationType,
    preferred_provider: CreativeProviderName | None,
    internal_provider: CreativeProvider,
    premium_provider: CreativeProvider | None,
) -> CreativeProvider:
    """Picks which CreativeProvider instance actually handles this
    request. `premium_provider` is already constructed and configured (or
    None if not configured — see app.dependencies.get_optional_higgsfield_provider),
    so this function never touches settings or credentials itself, and
    contains no provider-specific branching beyond the two abstract
    CreativeProvider instances it's handed."""
    wants_premium = preferred_provider is CreativeProviderName.HIGGSFIELD or creative_level in (
        _LEVELS_REQUIRING_PREMIUM_PROVIDER
    )
    if wants_premium:
        if premium_provider is None:
            raise NoSuitableProviderError(
                f"Creative level {creative_level.value!r} requires a premium creative provider "
                "(e.g. Higgsfield), but none is configured on this server."
            )
        if not premium_provider.supports(generation_type):
            raise CreativeCapabilityNotSupportedError(
                f"{premium_provider.name.value} does not support {generation_type.value!r} generation."
            )
        return premium_provider

    if not internal_provider.supports(generation_type):
        raise CreativeCapabilityNotSupportedError(
            f"{internal_provider.name.value} does not support {generation_type.value!r} generation — "
            "a premium provider is required for this generation type."
        )
    return internal_provider


def _call_provider(
    provider: CreativeProvider, generation_type: CreativeGenerationType, brief: CreativeBrief
) -> CreativeGenerationResult:
    if generation_type is CreativeGenerationType.WEBSITE_CONCEPT:
        return provider.generate_concept(brief)
    if generation_type is CreativeGenerationType.WEBSITE:
        return provider.generate_website(brief)
    if generation_type is CreativeGenerationType.IMAGE:
        return provider.generate_image(brief)
    if generation_type is CreativeGenerationType.VIDEO:
        return provider.generate_video(brief)
    return provider.generate_visual_asset(brief)


def orchestrate_generation(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    business_config: BusinessConfig,
    generation_type: CreativeGenerationType,
    internal_provider: CreativeProvider,
    premium_provider: CreativeProvider | None = None,
    assets: Sequence[AssetInput] = (),
    reviews: Sequence[ReviewInput] = (),
) -> CreativeGeneration:
    """Runs one generation request end to end and returns the persisted,
    terminal CreativeGeneration row — every call (first generation,
    regeneration, or a variation) goes through this same path uniformly;
    there is no separate "regenerate" code path; see this module's own
    docstring for why that's safe by construction. `assets`/`reviews` are
    the business's already-loaded, persisted rows (the caller — a router
    — fetches them via the repositories, this function touches only the
    session it's given, never a new query of its own for either).
    """
    creative = business_config.creative
    preferred_provider = None
    if creative.preferred_provider:
        try:
            preferred_provider = CreativeProviderName(creative.preferred_provider)
        except ValueError:
            # An unrecognized value (e.g. a provider not yet implemented)
            # falls back to level-based routing below rather than
            # crashing the whole generation request over a stale
            # preference.
            preferred_provider = None

    provider = select_provider(
        creative_level=creative.level,
        generation_type=generation_type,
        preferred_provider=preferred_provider,
        internal_provider=internal_provider,
        premium_provider=premium_provider,
    )

    brief = build_creative_brief(business_config=business_config, assets=assets, reviews=reviews)

    generation = CreativeGeneration(
        tenant_id=tenant_id,
        business_id=business_id,
        provider=provider.name,
        generation_type=generation_type,
        creative_level=creative.level,
        status=CreativeGenerationStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    CreativeGenerationRepository(session).add(generation)

    try:
        result = _call_provider(provider, generation_type, brief)
    except CreativeProviderError as exc:
        generation.status = CreativeGenerationStatus.FAILED
        generation.error = str(exc)
        generation.completed_at = datetime.now(UTC)
        return generation

    generation.status = result.status
    generation.external_reference = result.external_reference
    generation.credits_used = result.credits_used
    generation.estimated_cost = result.estimated_cost
    generation.generation_metadata = result.raw_metadata
    generation.completed_at = datetime.now(UTC)
    return generation
