"""HiggsfieldApiCreativeDirector consuming the P2.2 composed spec.

The real HiggsfieldApiClient is used over an httpx.MockTransport (no
network, no real Higgsfield call, no spend anywhere in this module), so
endpoint, payload field and reference count are verified end to end."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.creative.higgsfield.api_client import HiggsfieldApiClient, HiggsfieldInsufficientCreditsError
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
    CreativeBudgetTier,
)

SOUL = "higgsfield-ai/soul/reference"
NANO = "nano-banana"
PRESIGNED = "https://acct.r2.cloudflarestorage.com/biz/logo.png?X-Amz-Signature=SECRETSIG"
RESULT_URL = "https://d3example.cloudfront.net/out.png"


class _FakeStorage:
    provider_name = "r2"

    def __init__(self) -> None:
        self.keys: list[str] = []

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        self.keys.append(storage_key)
        return PRESIGNED


class _Gateway:
    """httpx.MockTransport handler recording every POST (a billable
    submission) and answering polls with a completed job."""

    def __init__(self, *, fail_with: int | None = None, result_url: str = RESULT_URL) -> None:
        self.posts: list[dict] = []
        self._fail_with = fail_with
        self._result_url = result_url

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append({"path": request.url.path, "body": json.loads(request.content)})
            if self._fail_with:
                return httpx.Response(self._fail_with, json={"detail": "not_enough_credits"})
            n = len(self.posts)
            return httpx.Response(
                200,
                json={
                    "status": "queued",
                    "request_id": f"r-{n}",
                    "status_url": f"https://api.higgsfield.ai/requests/r-{n}/status",
                    "cancel_url": f"https://api.higgsfield.ai/requests/r-{n}/cancel",
                },
            )
        return httpx.Response(200, json={"status": "completed", "images": [{"url": self._result_url}]})


def _director(gateway: _Gateway, model: str, **kwargs) -> HiggsfieldApiCreativeDirector:
    http_client = httpx.Client(transport=httpx.MockTransport(gateway), base_url="https://api.higgsfield.ai")
    client = HiggsfieldApiClient(key_id="kid", key_secret="ksecret", http_client=http_client)
    kwargs.setdefault("storage", _FakeStorage())
    return HiggsfieldApiCreativeDirector(client, job_type=model, **kwargs)


def _config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Cositas y Puntos crea amigurumi hechos a mano.",
        )
    )


def _asset(
    kind: AssetKind,
    category: AssetCategory,
    *,
    url: str = "https://cdn.example.com/a.png",
    r2_key: str | None = None,
) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(),
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        url=url,
        storage_provider="r2" if r2_key else None,
        storage_key=r2_key,
    )


def _r2_logo() -> CreativeBriefAsset:
    return _asset(AssetKind.LOGO, AssetCategory.LOGO, url="https://pub.example/logo.png", r2_key="biz/logo.png")


def _run(director, assets, *, hard_limit=None, **brief_kwargs):
    brief = build_creative_brief(business_config=_config(), **brief_kwargs)
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=hard_limit)
    return brief, budget, director.create_directions(brief, assets, budget)


def test_soul_reference_sends_exactly_one_reference_on_its_own_endpoint_field():
    gateway = _Gateway()
    assets = [
        _asset(AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE),
        _asset(AssetKind.IMAGE, AssetCategory.GALLERY),
        _r2_logo(),
    ]

    _run(_director(gateway, SOUL), assets)

    body = gateway.posts[0]["body"]
    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/reference"
    assert body["image_reference_url"] == PRESIGNED  # the R2-backed logo, resolved via a presigned URL
    assert "input_images" not in body
    assert isinstance(body["image_reference_url"], str)  # one reference, never a list
    assert body["aspect_ratio"] == "16:9"


def test_the_prompt_sent_treats_the_logo_as_identity_and_forbids_text():
    gateway = _Gateway()

    _run(_director(gateway, SOUL), [_r2_logo()])

    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "cositas" not in prompt  # the name would invite the model to render it
    assert "official brand logo" in prompt
    assert "do not reproduce, redraw, imitate or place the logo" in prompt
    assert "no words, letters, numbers or typography" in prompt
    assert "negative space" in prompt
    assert "avoid:" in prompt


def test_provenance_lists_reference_asset_ids_but_never_the_presigned_url():
    gateway = _Gateway()
    logo = _r2_logo()

    _, _, candidates = _run(_director(gateway, SOUL), [logo])

    [candidate] = candidates[:1]
    serialized = json.dumps(candidate.generation_metadata) + json.dumps(candidate.provider_metadata)
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["references"] == [
        {
            "asset_id": str(logo.id),
            "usage": "identity",
            "asset_kind": "logo",
            "asset_category": "logo",
            "source": "business_asset",
        }
    ]
    assert spec["purpose"] == "hero" and spec["provider"] == "higgsfield" and spec["model"] == SOUL
    assert spec["job_id"] == "r-1" and spec["prompt_version"]
    assert spec["validation"]["status"] == "passed"
    assert "SECRETSIG" not in serialized and "X-Amz" not in serialized and PRESIGNED not in serialized
    assert "ksecret" not in serialized and "kid" not in serialized.replace("provider", "")


def test_estimated_units_are_labelled_as_an_internal_estimate_not_provider_cost():
    gateway = _Gateway()

    _, budget, [candidate] = _run(_director(gateway, SOUL), [_r2_logo()], hard_limit=2.0)

    meta = candidate.generation_metadata
    assert meta["credits_used"] == 2.0 == meta["estimated_generation_units"]  # legacy key kept, alias added
    assert meta["credits_are_estimated"] is True
    assert "not_provider" in meta["cost_semantics"]


def test_hard_limit_two_at_the_default_estimate_makes_exactly_one_provider_submission():
    gateway = _Gateway()

    _, budget, candidates = _run(_director(gateway, SOUL), [_r2_logo()], hard_limit=2.0)

    assert len(gateway.posts) == 1
    assert len(candidates) == 1
    assert budget.credits_used == 2.0


def test_without_a_tight_limit_budget_behaviour_is_unchanged_three_explorations():
    gateway = _Gateway()

    _, _, candidates = _run(_director(gateway, SOUL), [_r2_logo()])

    assert len(gateway.posts) == 3 and len(candidates) == 3
    assert {c.generation_metadata["creative_spec"]["angle"] for c in candidates} != set()
    assert len({c.provider_metadata["angle"] for c in candidates}) == 3


def test_next_ranked_reference_is_used_when_the_top_one_cannot_be_resolved():
    gateway = _Gateway()
    unresolvable_logo = _asset(AssetKind.LOGO, AssetCategory.LOGO, url="http://insecure.example/logo.png")
    hero = _asset(AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE, url="https://cdn.example.com/hero.png")

    _, _, [candidate, *_] = _run(_director(gateway, SOUL), [unresolvable_logo, hero])

    assert gateway.posts[0]["body"]["image_reference_url"] == "https://cdn.example.com/hero.png"
    used = candidate.generation_metadata["creative_spec"]["references"]
    assert [r["asset_id"] for r in used] == [str(hero.id)]  # provenance reflects what was really sent
    assert used[0]["usage"] == "composition"


def test_product_purpose_selects_the_real_product_image_over_the_logo():
    gateway = _Gateway()
    product = _asset(AssetKind.IMAGE, AssetCategory.PRODUCT, url="https://cdn.example.com/product.png")

    _run(_director(gateway, SOUL), [_r2_logo(), product], purpose=AssetPurpose.PRODUCT)

    body = gateway.posts[0]["body"]
    assert body["image_reference_url"] == "https://cdn.example.com/product.png"
    assert "real product" in body["prompt"].lower()
    assert body["aspect_ratio"] == "1:1"


def test_nano_banana_still_receives_several_references_in_its_own_field():
    gateway = _Gateway()
    assets = [
        _r2_logo(),
        _asset(AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE, url="https://cdn.example.com/hero.png"),
        _asset(AssetKind.IMAGE, AssetCategory.GALLERY, url="https://cdn.example.com/gallery.png"),
    ]

    _run(_director(gateway, NANO), assets)

    body = gateway.posts[0]["body"]
    assert gateway.posts[0]["path"] == "/nano-banana"
    assert len(body["input_images"]) == 3
    assert "image_reference_url" not in body


def test_no_assets_sends_no_reference_and_says_so_in_the_prompt():
    gateway = _Gateway()

    _run(_director(gateway, NANO), [])

    body = gateway.posts[0]["body"]
    assert "input_images" not in body and "image_reference_url" not in body
    assert "no reference images are supplied" in body["prompt"].lower()


def test_unavailable_assets_are_excluded_end_to_end():
    gateway = _Gateway()
    broken = SimpleNamespace(
        id=uuid4(),
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/broken.png",
        storage_provider=None,
        storage_key=None,
        unavailable_reason="object_missing",
        alt_text=None,
    )
    healthy = SimpleNamespace(
        id=uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.GALLERY,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/healthy.png",
        storage_provider=None,
        storage_key=None,
        unavailable_reason=None,
        alt_text=None,
    )
    brief = build_creative_brief(business_config=_config(), assets=[broken, healthy])
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)

    _director(gateway, SOUL).create_directions(brief, brief.available_assets, budget)

    assert gateway.posts[0]["body"]["image_reference_url"] == "https://cdn.example.com/healthy.png"


def test_unsupported_aspect_ratio_is_omitted_rather_than_sent():
    director = _director(_Gateway(), SOUL)
    assert director._supported_aspect_ratio("16:9") == "16:9"
    assert director._supported_aspect_ratio("21:9") is None  # not in soul/reference's supported set


def test_a_failed_validation_is_recorded_but_the_paid_result_is_still_returned():
    gateway = _Gateway(result_url="https://d3example.cloudfront.net/out.gif")

    _, _, [candidate, *_] = _run(_director(gateway, SOUL), [_r2_logo()], hard_limit=2.0)

    validation = candidate.generation_metadata["creative_spec"]["validation"]
    assert validation["status"] == "failed"
    assert validation["visual_qa"] == "not_performed"
    assert candidate.references == ["https://d3example.cloudfront.net/out.gif"]


def test_the_concept_narrative_keeps_the_business_name_for_studio_and_the_frontend_engine():
    _, _, candidates = _run(_director(_Gateway(), SOUL), [_r2_logo()], hard_limit=2.0)
    assert "Cositas y Puntos" in candidates[0].concept.narrative


def test_provider_errors_stay_structured_and_only_one_submission_is_attempted():
    gateway = _Gateway(fail_with=403)

    with pytest.raises(HiggsfieldInsufficientCreditsError):
        _run(_director(gateway, SOUL), [_r2_logo()])

    assert len(gateway.posts) == 1  # no retry, no second exploration after a failure


def test_develop_keeps_the_purpose_and_brand_mode_of_the_direction_it_deepens():
    gateway = _Gateway()
    director = _director(gateway, SOUL)
    brief, budget, [selected, *_] = _run(
        director,
        [_r2_logo()],
        hard_limit=2.0,
        purpose=AssetPurpose.BACKGROUND,
        brand_strategy=BrandStrategy.NEW_DIRECTION,
    )
    default_brief = build_creative_brief(business_config=_config())  # request-time defaults: HERO / configured mode

    developed = director.develop_direction(
        selected, default_brief, [], CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    )

    develop_prompt = gateway.posts[-1]["body"]["prompt"].lower()
    assert "full-width background" in develop_prompt  # not silently switched to a hero
    assert "continue the same world" in develop_prompt
    assert "cositas" not in develop_prompt
    assert gateway.posts[-1]["body"]["image_reference_url"] == RESULT_URL  # anchored on the previous result
    assert developed.generation_metadata["stage"] == "developed"
    assert developed.generation_metadata["creative_spec"]["purpose"] == "background"
