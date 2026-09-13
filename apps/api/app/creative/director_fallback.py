"""FallbackCreativeDirector — the single provider-outage safety net for
CreativeDirectorProvider.create_directions/develop_direction: Higgsfield
being unconfigured, or its configured REST model returning
404 model_not_found / 401 Unauthorized on the very first exploration
call, must degrade the Generative Website workflow to
InternalCreativeDirector rather than make it unusable end-to-end — a
Higgsfield outage or workspace entitlement gap (see
docs/higgsfield-integration.md) should degrade creative quality, never
stop Studio's "Generate creative directions" button from working at all.

Double-billing safety (the reason this exists as its own small wrapper
rather than a try/except sprinkled into app.routers.creative): a fallback
is only ever attempted when the primary's create_directions() raises —
and app.creative.higgsfield.director._HiggsfieldDirectorBase.create_directions
only raises when zero candidates were produced, which is only possible
when the very FIRST exploration call failed before Higgsfield ever issued
a request_id (every later iteration's failure is swallowed and just stops
further exploration, returning whatever candidates already succeeded — see
that method's own docstring). _SAFE_FALLBACK reasons below therefore cover
only exceptions app.creative.higgsfield.api_client.HiggsfieldApiClient.submit
raises before any HTTP response could have granted a request_id
(an unrecognized/misconfigured model id, or a 401/404 response to the
POST that would have started a job) — never a status reached by polling
an already-accepted job (a timeout, `failed`, `nsfw`, `canceled`, or
insufficient credits, all of which are deliberately NOT here and are
re-raised unchanged, exactly as before this wrapper existed). A real,
billed Higgsfield attempt is therefore never silently repeated against
InternalCreativeDirector.
"""

from collections.abc import Sequence

from app.creative.director import CreativeDirectorProvider
from app.creative.higgsfield.api_client import HiggsfieldApiUnavailableError, HiggsfieldModelUnavailableError
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import CreativeDirection
from app.domain.enums import CreativeProviderName

NOT_CONFIGURED_REASON = "higgsfield_not_configured"


def _tag_as_fallback(candidates: list[CreativeDirection], *, reason: str) -> list[CreativeDirection]:
    for candidate in candidates:
        candidate.provider_metadata = {
            **candidate.provider_metadata,
            "provider": "internal_fallback",
            "fallback_reason": reason,
        }
    return candidates


class FallbackCreativeDirector(CreativeDirectorProvider):
    """Wraps a (possibly absent) Higgsfield-backed primary director with
    InternalCreativeDirector as a safety net. `name` is a fixed
    ClassVar (CreativeProviderName.HIGGSFIELD, same as every other
    CreativeDirectorProvider implementation) describing the *nominal*
    provider chain this instance was built with — read by
    app.creative.director_orchestrator.orchestrate_create_directions
    *before* create_directions runs, for that coarse, request-level
    CreativeGeneration.provider audit column. The real, per-call outcome
    lives on each returned CreativeDirection's own
    `provider_metadata['provider']` (`"higgsfield"` or
    `"internal_fallback"`) — that field, never `.name`, is what Studio and
    every test in this module actually reads (P2.14)."""

    name = CreativeProviderName.HIGGSFIELD

    def __init__(self, *, primary: CreativeDirectorProvider | None, fallback: CreativeDirectorProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        if self._primary is None:
            return _tag_as_fallback(
                self._fallback.create_directions(brief, assets, budget), reason=NOT_CONFIGURED_REASON
            )
        try:
            return self._primary.create_directions(brief, assets, budget)
        except HiggsfieldModelUnavailableError:
            reason = "higgsfield_model_unavailable"
        except HiggsfieldApiUnavailableError:
            reason = "higgsfield_unavailable"
        return _tag_as_fallback(self._fallback.create_directions(brief, assets, budget), reason=reason)

    def develop_direction(
        self,
        selected: CreativeDirection,
        brief: CreativeBrief,
        assets: Sequence[CreativeBriefAsset],
        budget: CreativeBudget,
    ) -> CreativeDirection:
        # Route by which provider actually created `selected` (P2.14: never
        # a second, unrelated concept) — never by which one is configured
        # right now, since availability can change between create and
        # develop. An internal-fallback-origin direction has no real
        # generated reference image for Higgsfield to anchor a
        # continuation on, so it always stays with the fallback director.
        primary_made_it = selected.provider_metadata.get("provider") == CreativeProviderName.HIGGSFIELD.value
        if self._primary is not None and primary_made_it:
            return self._primary.develop_direction(selected, brief, assets, budget)
        return self._fallback.develop_direction(selected, brief, assets, budget)
