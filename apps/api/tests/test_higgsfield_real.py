"""REAL, non-mocked proof of the P2.1 production Higgsfield REST
integration (HiggsfieldApiCreativeDirector against the real
https://api.higgsfield.ai, real server-side API key pair). Marked
`real_provider` and excluded from the default `pytest` invocation (see
pyproject.toml's addopts) — run explicitly with
`pytest -m real_provider tests/test_higgsfield_real.py`, mirroring
tests/test_frontend_engine_real.py's own real-Anthropic-provider test.

Uses the already-established EXAMPLE_COSITAS_Y_PUNTOS_CONFIG fixture (the
real business this P2.1 production pass targets) but spends genuinely new
Higgsfield credits — unlike tests/test_contrast_generative_output.py's
reuse of tests/fixtures/cositas_creative_direction.json (an already-paid
CLI-path result), this test specifically proves the NEW REST integration
end-to-end and cannot reuse that old fixture for that purpose. Budgeted
via CreativeBudget's own STANDARD-tier hard limit (20 credits) — the same
ceiling this task's real proof was authorized against.
"""

import time

import pytest

from app.config import settings
from app.creative.critic import select_direction
from app.creative.higgsfield.api_client import HiggsfieldApiClient
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.enums import CreativeBudgetTier

pytestmark = pytest.mark.real_provider


@pytest.mark.skipif(
    not (settings.higgsfield_api_key_id and settings.higgsfield_api_key_secret),
    reason="HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET not configured",
)
def test_real_higgsfield_api_creative_director_produces_and_develops_a_direction():
    started = time.monotonic()
    print(
        "[real_provider] provider availability check: "
        f"HIGGSFIELD_API_KEY_ID configured, base_url={settings.higgsfield_api_base_url}"
    )

    brief = build_creative_brief(business_config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG)
    client = HiggsfieldApiClient(
        key_id=settings.higgsfield_api_key_id,
        key_secret=settings.higgsfield_api_key_secret,
        base_url=settings.higgsfield_api_base_url,
        timeout_seconds=settings.higgsfield_api_timeout_seconds,
    )
    director = HiggsfieldApiCreativeDirector(
        client, estimated_credits_per_call=settings.higgsfield_api_estimated_credits_per_call
    )
    # STANDARD's own default hard limit (20.0) is exactly this task's
    # authorized real-credit ceiling — reused verbatim, not overridden.
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)

    print("[real_provider] create_directions: submitting 3 real Higgsfield requests")
    candidates = director.create_directions(brief, [], budget)
    print(
        f"[real_provider] create_directions complete: {len(candidates)} candidates, "
        f"{budget.credits_used} credits used so far"
    )
    for candidate in candidates:
        request_id = candidate.provider_metadata.get("job_id")
        print(f"[real_provider]   request_id={request_id} result_url={candidate.references}")

    assert len(candidates) == 3
    assert all(candidate.references for candidate in candidates)  # every candidate has a real result URL
    assert all(EXAMPLE_COSITAS_Y_PUNTOS_CONFIG.business_profile.name in c.concept.narrative for c in candidates)

    print("[real_provider] running the real critic (select_direction)")
    select_direction(candidates, brief)
    selected = next(c for c in candidates if c.is_recommended)
    print(f"[real_provider] critic selected: {selected.concept.name!r} — {selected.selection_rationale}")
    assert selected.selection_rationale

    print("[real_provider] develop_direction: submitting 3 more real Higgsfield requests")
    developed = director.develop_direction(selected, brief, [], budget)
    print(
        f"[real_provider] develop_direction complete: {len(developed.references)} total references, "
        f"{budget.credits_used} credits used total"
    )

    assert developed.concept.name == selected.concept.name  # same direction, deepened — not a new concept
    assert len(developed.references) > len(selected.references)
    assert developed.generation_metadata["stage"] == "developed"
    assert budget.credits_used <= 20.0  # the hard cap this task was authorized against

    total_ms = round((time.monotonic() - started) * 1000)
    print(f"[real_provider] test total duration: {total_ms}ms, total credits used: {budget.credits_used}")
