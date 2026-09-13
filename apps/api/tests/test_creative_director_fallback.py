"""FallbackCreativeDirector (app.creative.director_fallback) — the P2.1
continuation fix for the production blocker where a Higgsfield workspace
entitlement gap (404 model_not_found) made the whole Generative Website
workflow unusable. Every Higgsfield backend here is a fake, in-memory
HiggsfieldApiClient-shaped object (same pattern as
test_higgsfield_api_director.py) — no real network/credit spend anywhere
in this module.

Double-billing safety is the central property under test: fallback must
trigger for a pre-acceptance failure (model_not_found, unavailable, not
configured) and must NEVER trigger once Higgsfield already produced at
least one real candidate (i.e. already issued a request_id and started
billing)."""

import httpx
import pytest

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield.api_client import (
    HiggsfieldApiClient,
    HiggsfieldApiUnavailableError,
    HiggsfieldInsufficientCreditsError,
    HiggsfieldModelUnavailableError,
    HiggsfieldTimeoutError,
)
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.creative.higgsfield.models import HiggsfieldJobResult
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.budget import BudgetExceededError, CreativeBudget
from app.domain.enums import BusinessVertical, CreativeBudgetTier, CreativeProviderName


def _brief():
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Amigurumi hechos a mano.",
        )
    )
    return build_creative_brief(business_config=config)


def _job(job_id: str, url: str) -> HiggsfieldJobResult:
    return HiggsfieldJobResult(job_id=job_id, job_type="nano-banana", status="completed", result_url=url)


class _FakeApiClient:
    """Same fake-backend shape as test_higgsfield_api_director.py's own
    _FakeApiClient — records every create() call, returns a scripted
    sequence of HiggsfieldJobResult (or raises)."""

    def __init__(self, results: list) -> None:
        self._results = iter(results)
        self.calls = 0

    def create(
        self, job_type, *, prompt, image_references=None, aspect_ratio=None, resolution=None, wait_timeout="4m"
    ):
        self.calls += 1
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


def _budget() -> CreativeBudget:
    return CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)


# --- 5/6. pre-acceptance failure -> Internal fallback -----------------------


def test_model_not_found_before_any_candidate_falls_back_to_internal():
    higgsfield = HiggsfieldApiCreativeDirector(
        _FakeApiClient([HiggsfieldModelUnavailableError("...", detail="model_not_found")])
    )
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert len(candidates) == 1
    assert candidates[0].provider_metadata["provider"] == "internal_fallback"
    assert candidates[0].provider_metadata["fallback_reason"] == "higgsfield_model_unavailable"


def test_higgsfield_unavailable_before_any_candidate_falls_back_to_internal():
    higgsfield = HiggsfieldApiCreativeDirector(
        _FakeApiClient(
            [
                HiggsfieldApiUnavailableError(
                    "HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are not configured on this server."
                )
            ]
        )
    )
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert candidates[0].provider_metadata["provider"] == "internal_fallback"
    assert candidates[0].provider_metadata["fallback_reason"] == "higgsfield_unavailable"


def test_missing_higgsfield_configuration_falls_back_to_internal():
    """primary=None mirrors app.dependencies.get_optional_higgsfield_director
    returning None when HIGGSFIELD_API_KEY_ID/_SECRET aren't set."""
    director = FallbackCreativeDirector(primary=None, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert candidates[0].provider_metadata["provider"] == "internal_fallback"
    assert candidates[0].provider_metadata["fallback_reason"] == "higgsfield_not_configured"


def test_unsupported_configured_model_id_also_falls_back_to_internal():
    """An unrecognized HIGGSFIELD_API_MODEL raises HiggsfieldApiUnavailableError
    from HiggsfieldApiClient.submit (see test_higgsfield_model_registry.py)
    — the same safe-to-fall-back-on exception as a missing key."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must never be called
        raise AssertionError("no HTTP request should be made for an unrecognized model id")

    client = HiggsfieldApiClient(
        key_id="k", key_secret="s", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    higgsfield = HiggsfieldApiCreativeDirector(client, job_type="not-a-real-model")
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert candidates[0].provider_metadata["provider"] == "internal_fallback"
    assert candidates[0].provider_metadata["fallback_reason"] == "higgsfield_unavailable"


# --- Fallback is FORBIDDEN for anything else --------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        HiggsfieldInsufficientCreditsError("...", detail="not_enough_credits"),
        HiggsfieldTimeoutError("did not reach a terminal state within 4m."),
    ],
)
def test_every_other_higgsfield_failure_is_never_a_fallback_trigger(exc):
    higgsfield = HiggsfieldApiCreativeDirector(_FakeApiClient([exc]))
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    with pytest.raises(type(exc)):
        director.create_directions(_brief(), [], _budget())


def test_budget_exhaustion_is_never_a_fallback_trigger():
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=0.5)
    higgsfield = HiggsfieldApiCreativeDirector(
        _FakeApiClient([_job("r-1", "https://x/1.png")]), estimated_credits_per_call=2.0
    )
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    with pytest.raises(BudgetExceededError):
        director.create_directions(_brief(), [], budget)


# --- 7/8. accepted Higgsfield job never falls back / never a 2nd generation --


def test_a_partial_success_never_triggers_fallback_even_if_a_later_iteration_fails():
    """iteration 1 succeeds (Higgsfield already issued a request_id — real
    spend happened); iteration 2 fails with model_not_found. create_directions
    only raises when EMPTY (see _HiggsfieldDirectorBase's own docstring), so
    this never reaches FallbackCreativeDirector's except clause at all —
    proving an accepted job is never followed by a second (Internal)
    generation."""
    fake = _FakeApiClient(
        [_job("r-1", "https://x/1.png"), HiggsfieldModelUnavailableError("...", detail="model_not_found")]
    )
    higgsfield = HiggsfieldApiCreativeDirector(fake)
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert len(candidates) == 1
    assert candidates[0].provider_metadata["provider"] == CreativeProviderName.HIGGSFIELD.value
    assert fake.calls == 2  # exploration stopped after the failure — no Internal call was ever made


def test_a_post_acceptance_timeout_never_causes_a_second_generation():
    fake = _FakeApiClient([_job("r-1", "https://x/1.png"), HiggsfieldTimeoutError("timed out mid-poll")])
    higgsfield = HiggsfieldApiCreativeDirector(fake)
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())

    candidates = director.create_directions(_brief(), [], _budget())

    assert len(candidates) == 1
    assert candidates[0].provider_metadata["provider"] == CreativeProviderName.HIGGSFIELD.value
    assert fake.calls == 2  # never a 3rd (Internal) attempt


# --- develop_direction routes by the origin provider, not current config ----


def test_develop_direction_routes_an_internal_fallback_origin_direction_to_internal():
    director = FallbackCreativeDirector(primary=None, fallback=InternalCreativeDirector())
    [selected] = director.create_directions(_brief(), [], _budget())

    developed = director.develop_direction(selected, _brief(), [], _budget())

    assert developed.generation_metadata["stage"] == "developed"
    assert developed.provider_metadata["provider"] == "internal_fallback"


def test_develop_direction_routes_a_real_higgsfield_origin_direction_to_higgsfield():
    fake = _FakeApiClient([_job("r-1", "https://x/1.png")])
    higgsfield = HiggsfieldApiCreativeDirector(fake)
    director = FallbackCreativeDirector(primary=higgsfield, fallback=InternalCreativeDirector())
    [selected] = director.create_directions(_brief(), [], _budget())
    assert selected.provider_metadata["provider"] == "higgsfield"

    develop_fake = _FakeApiClient(
        [_job("r-1a", "https://x/1a.png"), _job("r-1b", "https://x/1b.png"), _job("r-1c", "https://x/1c.png")]
    )
    higgsfield._client = develop_fake  # noqa: SLF001 — swap the fake backend for the develop phase

    director.develop_direction(selected, _brief(), [], _budget())

    assert develop_fake.calls == 3  # the real Higgsfield backend deepened it, not InternalCreativeDirector's no-op
