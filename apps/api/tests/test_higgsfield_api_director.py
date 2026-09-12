"""HiggsfieldApiCreativeDirector (app.creative.higgsfield.director) — the
production REST-backed Creative Director. HiggsfieldApiClient is a fake
in-memory stand-in throughout (no real network/credit spend anywhere in
this module); verifies budget-before-spend discipline with the
*estimated* cost (no real REST cost-estimate endpoint exists), real-asset
reference selection/propagation (logo/hero preferred, never every asset),
and develop_direction anchoring on the previous result's own URL (REST has
no "reference by job id" the way the CLI backend does)."""

from uuid import uuid4

import pytest

from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.creative.higgsfield.models import HiggsfieldJobResult
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BusinessVertical, CreativeBudgetTier


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


def _asset(*, kind: AssetKind, category: AssetCategory, url: str) -> CreativeBriefAsset:
    return CreativeBriefAsset(id=uuid4(), kind=kind, category=category, origin=AssetOrigin.UPLOADED, url=url)


class _FakeApiClient:
    """Records every create() call it receives; returns a scripted
    sequence of HiggsfieldJobResult (or raises) — no HTTP, no credits."""

    def __init__(self, results: list) -> None:
        self._results = iter(results)
        self.calls: list[dict] = []

    def create(
        self, job_type, *, prompt, image_references=None, aspect_ratio=None, resolution=None, wait_timeout="4m"
    ):
        self.calls.append(
            {
                "job_type": job_type,
                "prompt": prompt,
                "image_references": image_references,
                "aspect_ratio": aspect_ratio,
            }
        )
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


def _job(job_id: str, url: str) -> HiggsfieldJobResult:
    return HiggsfieldJobResult(job_id=job_id, job_type="nano-banana", status="completed", result_url=url)


def test_create_directions_uses_estimated_credits_and_marks_them_as_estimated():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    client = _FakeApiClient(
        [_job("r-1", "https://x/1.png"), _job("r-2", "https://x/2.png"), _job("r-3", "https://x/3.png")]
    )
    director = HiggsfieldApiCreativeDirector(client, estimated_credits_per_call=1.5)

    candidates = director.create_directions(brief, [], budget)

    assert len(candidates) == 3
    assert budget.credits_used == 4.5  # 3 * 1.5, the configured estimate — no real REST cost endpoint exists
    assert all(c.generation_metadata["credits_are_estimated"] is True for c in candidates)
    assert {c.references[0] for c in candidates} == {"https://x/1.png", "https://x/2.png", "https://x/3.png"}
    assert all(brief.business_name in c.concept.narrative for c in candidates)


def test_create_directions_stops_gracefully_on_budget_exhaustion():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=3.0)
    client = _FakeApiClient([_job("r-1", "https://x/1.png"), _job("r-2", "https://x/2.png")])
    director = HiggsfieldApiCreativeDirector(client, estimated_credits_per_call=1.5)

    candidates = director.create_directions(brief, [], budget)

    assert len(candidates) == 2  # a third 1.5-credit call would exceed the 3.0 hard limit
    assert budget.credits_used == 3.0


def test_reference_urls_prefer_logo_then_hero_never_every_asset():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    client = _FakeApiClient(
        [_job("r-1", "https://x/1.png"), _job("r-2", "https://x/2.png"), _job("r-3", "https://x/3.png")]
    )
    director = HiggsfieldApiCreativeDirector(client, estimated_credits_per_call=1.0, max_reference_assets=2)

    assets = [
        _asset(kind=AssetKind.IMAGE, category=AssetCategory.OTHER, url="https://cdn.example.com/other.png"),
        _asset(kind=AssetKind.IMAGE, category=AssetCategory.HERO_CANDIDATE, url="https://cdn.example.com/hero.png"),
        _asset(kind=AssetKind.LOGO, category=AssetCategory.LOGO, url="https://cdn.example.com/logo.png"),
        _asset(kind=AssetKind.IMAGE, category=AssetCategory.LOW_QUALITY, url="https://cdn.example.com/bad.png"),
    ]

    director.create_directions(brief, assets, budget)

    first_call_refs = client.calls[0]["image_references"]
    assert first_call_refs == ["https://cdn.example.com/logo.png", "https://cdn.example.com/hero.png"]
    assert "https://cdn.example.com/bad.png" not in first_call_refs  # never a LOW_QUALITY asset
    assert len(first_call_refs) == 2  # capped at max_reference_assets, never every asset in the library


def test_reference_urls_resolve_a_root_relative_asset_url_against_asset_base_url():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    client = _FakeApiClient(
        [_job("r-1", "https://x/1.png"), _job("r-2", "https://x/2.png"), _job("r-3", "https://x/3.png")]
    )
    director = HiggsfieldApiCreativeDirector(client, asset_base_url="https://api.example.com")

    assets = [_asset(kind=AssetKind.LOGO, category=AssetCategory.LOGO, url="/uploads/biz/logo.png")]
    director.create_directions(brief, assets, budget)

    assert client.calls[0]["image_references"] == ["https://api.example.com/uploads/biz/logo.png"]


def test_reference_urls_are_empty_without_asset_base_url_for_a_root_relative_url():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    client = _FakeApiClient(
        [_job("r-1", "https://x/1.png"), _job("r-2", "https://x/2.png"), _job("r-3", "https://x/3.png")]
    )
    director = HiggsfieldApiCreativeDirector(client)  # no asset_base_url configured

    assets = [_asset(kind=AssetKind.LOGO, category=AssetCategory.LOGO, url="/uploads/biz/logo.png")]
    director.create_directions(brief, assets, budget)

    # Honest degradation, never a fabricated substitute image: no usable
    # reference URL means no reference is sent, not a crash.
    assert client.calls[0]["image_references"] is None


def test_develop_direction_anchors_on_the_selected_result_url_not_a_job_id():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    client = _FakeApiClient([_job("r-1", "https://x/1.png")])
    director = HiggsfieldApiCreativeDirector(client)
    [selected] = director.create_directions(brief, [], budget)
    assert selected.references == ["https://x/1.png"]

    develop_client = _FakeApiClient(
        [_job("r-1a", "https://x/1a.png"), _job("r-1b", "https://x/1b.png"), _job("r-1c", "https://x/1c.png")]
    )
    director._client = develop_client  # noqa: SLF001 — swap the fake backend for the develop phase of this test
    developed = director.develop_direction(selected, brief, [], budget)

    assert developed.concept.name == selected.concept.name  # same direction, not a new concept
    assert set(developed.references) == {
        "https://x/1.png",
        "https://x/1a.png",
        "https://x/1b.png",
        "https://x/1c.png",
    }
    assert all(call["image_references"] == ["https://x/1.png"] for call in develop_client.calls)
    assert developed.generation_metadata["stage"] == "developed"


def test_create_directions_raises_when_zero_candidates_could_be_afforded():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=0.5)
    client = _FakeApiClient([_job("r-1", "https://x/1.png")])
    director = HiggsfieldApiCreativeDirector(client, estimated_credits_per_call=2.0)

    with pytest.raises(RuntimeError):
        director.create_directions(brief, [], budget)
    assert budget.credits_used == 0.0
