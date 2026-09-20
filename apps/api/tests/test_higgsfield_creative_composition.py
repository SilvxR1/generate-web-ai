"""HiggsfieldApiCreativeDirector consuming the P2.3 plan, reference strategy
and model router.

The real HiggsfieldApiClient is used over an httpx.MockTransport (no
network, no real Higgsfield call, no spend anywhere in this module), so
endpoint, payload field and reference count are verified end to end."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield import director as director_module
from app.creative.higgsfield.api_client import (
    HiggsfieldApiClient,
    HiggsfieldApiUnavailableError,
    HiggsfieldInsufficientCreditsError,
    HiggsfieldNoSuitableModelError,
    registered_models,
)
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
    CreativeLevel,
)

SOUL_REFERENCE = "higgsfield-ai/soul/reference"
SOUL_STANDARD = "higgsfield-ai/soul/standard"
NANO = "nano-banana"
PRESIGNED = "https://acct.r2.cloudflarestorage.com/biz/product.png?X-Amz-Signature=SECRETSIG"
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

    def __init__(self, *, fail_with: tuple[int, str] | None = None, result_url: str = RESULT_URL) -> None:
        self.posts: list[dict] = []
        self._fail_with = fail_with
        self._result_url = result_url

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append({"path": request.url.path, "body": json.loads(request.content)})
            if self._fail_with:
                status, detail = self._fail_with
                return httpx.Response(status, json={"detail": detail})
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


def _director(gateway: _Gateway, model: str = SOUL_REFERENCE, **kwargs) -> HiggsfieldApiCreativeDirector:
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
    return _asset(AssetKind.LOGO, AssetCategory.LOGO, url="https://pub.example/logo.jpg", r2_key="biz/logo.jpg")


def _r2_product() -> CreativeBriefAsset:
    return _asset(
        AssetKind.IMAGE, AssetCategory.PRODUCT, url="https://pub.example/product.png", r2_key="biz/product.png"
    )


def _run(director, assets, *, hard_limit=None, **brief_kwargs):
    brief = build_creative_brief(business_config=_config(), **brief_kwargs)
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=hard_limit)
    return brief, budget, director.create_directions(brief, assets, budget)


# --- the Cositas regression: HERO + PRESERVE + PROFESSIONAL + real logo --------


def test_cositas_regression_the_logo_is_never_sent_and_soul_reference_is_not_used():
    """The real experiments: soul/reference + the logo recreated the logo and
    its name twice. Same request now: the logo informs the brand profile only,
    nothing visual is sent, and a no-reference model is routed to."""
    gateway = _Gateway()
    logo = _r2_logo()

    _, _, [candidate, *_] = _run(
        _director(gateway, SOUL_REFERENCE),  # HIGGSFIELD_API_MODEL as configured in production
        [logo],
        hard_limit=2.0,
        purpose=AssetPurpose.HERO,
        brand_strategy=BrandStrategy.PRESERVE,
        creative_level=CreativeLevel.PROFESSIONAL,
    )

    [post] = gateway.posts
    assert post["path"] == "/higgsfield-ai/soul/standard"  # NOT /higgsfield-ai/soul/reference
    assert "image_reference_url" not in post["body"] and "input_images" not in post["body"]
    assert post["body"]["aspect_ratio"] == "16:9"

    spec = candidate.generation_metadata["creative_spec"]
    assert spec["brand_source_asset_ids"] == [str(logo.id)]  # the logo informed the profile...
    assert spec["provider_reference_asset_ids"] == []  # ...and was NOT sent to the model
    assert spec["references"] == []
    assert spec["model"] == SOUL_STANDARD == candidate.provider_metadata["job_type"]
    assert spec["model_selection"]["selected"] == SOUL_STANDARD
    assert spec["model_selection"]["reason"].startswith("configured_model_unsuitable:requires_a_reference")
    assert {"model_id": SOUL_REFERENCE, "reason": "requires_a_reference_but_none_is_wanted"} in spec["model_selection"][
        "rejected"
    ]
    assert spec["reference_strategy"]["policy"] == "no_visual_reference"
    assert spec["text_policy"] == "no_generated_text"


def test_hero_background_and_texture_with_a_logo_only_business_send_nothing_visual():
    for purpose in (AssetPurpose.HERO, AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE):
        gateway = _Gateway()

        _run(_director(gateway), [_r2_logo()], hard_limit=2.0, purpose=purpose)

        body = gateway.posts[0]["body"]
        assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/standard"
        assert "image_reference_url" not in body and "input_images" not in body


def test_the_prompt_conveys_no_logo_no_name_and_forbids_text():
    gateway = _Gateway()

    _run(_director(gateway), [_r2_logo()], hard_limit=2.0)

    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "cositas" not in prompt  # the name is never reintroduced
    assert "reference image" not in prompt  # nothing visual is sent, so none is described
    assert "no text, lettering, pseudo-text, signs, labels, logos" in prompt
    assert "negative space" in prompt and "wide 16:9" in prompt


# --- product references and the legitimate soul/reference path --------------------


def test_a_real_product_image_is_a_required_reference_and_soul_reference_still_works():
    gateway = _Gateway()
    storage = _FakeStorage()
    product = _r2_product()

    _, _, [candidate, *_] = _run(
        _director(gateway, SOUL_REFERENCE, storage=storage),
        [_r2_logo(), product],
        hard_limit=2.0,
        purpose=AssetPurpose.PRODUCT,
    )

    [post] = gateway.posts
    assert post["path"] == "/higgsfield-ai/soul/reference"
    assert post["body"]["image_reference_url"] == PRESIGNED  # exactly one, via the R2 presign
    assert isinstance(post["body"]["image_reference_url"], str)
    assert storage.keys == ["biz/product.png"]  # only the product was signed — never the logo
    assert "real product" in post["body"]["prompt"].lower()
    assert post["body"]["aspect_ratio"] == "1:1"
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["provider_reference_asset_ids"] == [str(product.id)]
    assert spec["references"][0]["usage"] == "product"
    assert spec["model_selection"]["reason"] == "configured_model_satisfies_requirements"


def test_a_product_request_without_a_real_product_image_stops_before_any_submission():
    gateway = _Gateway()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    brief = build_creative_brief(business_config=_config(), purpose=AssetPurpose.PRODUCT)

    with pytest.raises(HiggsfieldNoSuitableModelError) as excinfo:
        _director(gateway).create_directions(brief, [_r2_logo()], budget)

    assert excinfo.value.reason_code == "product_reference_missing"
    assert gateway.posts == [] and budget.credits_used == 0.0  # nothing submitted, nothing spent


def test_product_reference_is_never_the_logo_even_when_only_the_logo_exists():
    gateway = _Gateway()
    with pytest.raises(HiggsfieldNoSuitableModelError):
        _run(_director(gateway), [_r2_logo()], purpose=AssetPurpose.PRODUCT)
    assert gateway.posts == []


def test_nano_banana_still_receives_its_own_reference_field_for_optional_style_references():
    gateway = _Gateway()
    photo = _asset(AssetKind.IMAGE, AssetCategory.GALLERY, url="https://cdn.example.com/gallery.png")

    _run(_director(gateway, NANO), [_r2_logo(), photo], hard_limit=2.0, purpose=AssetPurpose.SECTION)

    body = gateway.posts[0]["body"]
    assert gateway.posts[0]["path"] == "/nano-banana"
    assert body["input_images"] == [{"type": "image_url", "image_url": "https://cdn.example.com/gallery.png"}]
    assert "image_reference_url" not in body


def test_nano_banana_hero_needs_no_reference():
    gateway = _Gateway()

    _run(_director(gateway, NANO), [_r2_logo()], hard_limit=2.0)

    assert gateway.posts[0]["path"] == "/nano-banana"
    assert "input_images" not in gateway.posts[0]["body"]


def test_an_optional_reference_that_cannot_be_resolved_reroutes_to_a_no_reference_model():
    gateway = _Gateway()
    unresolvable = _asset(AssetKind.IMAGE, AssetCategory.GALLERY, url="http://insecure.example/g.png")

    _, _, [candidate, *_] = _run(
        _director(gateway, SOUL_REFERENCE), [unresolvable], hard_limit=2.0, purpose=AssetPurpose.SECTION
    )

    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/standard"  # soul/reference can't run reference-less
    assert candidate.generation_metadata["creative_spec"]["provider_reference_asset_ids"] == []


def test_an_optional_reference_is_dropped_when_the_selected_model_cannot_take_one():
    gateway = _Gateway()
    photo = _asset(AssetKind.IMAGE, AssetCategory.GALLERY, url="https://cdn.example.com/g.png")

    _, _, [candidate, *_] = _run(
        _director(gateway, SOUL_STANDARD), [photo], hard_limit=2.0, purpose=AssetPurpose.EDITORIAL
    )

    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/standard"
    assert "image_reference_url" not in gateway.posts[0]["body"]
    assert candidate.generation_metadata["creative_spec"]["model_selection"]["dropped_optional_references"] is True


# --- unavailable assets, non-images, provenance safety -------------------------------


def test_unavailable_and_non_image_assets_are_never_references():
    def row(kind, unavailable_reason=None):
        return SimpleNamespace(
            id=uuid4(),
            kind=kind,
            category=AssetCategory.PRODUCT,
            origin=AssetOrigin.UPLOADED,
            storage_url="https://cdn.example.com/x.png",
            storage_provider=None,
            storage_key=None,
            unavailable_reason=unavailable_reason,
            alt_text=None,
        )

    broken, video, healthy = row(AssetKind.IMAGE, "object_missing"), row(AssetKind.VIDEO), row(AssetKind.IMAGE)
    healthy.storage_url = "https://cdn.example.com/healthy.png"
    brief = build_creative_brief(
        business_config=_config(), assets=[broken, video, healthy], purpose=AssetPurpose.PRODUCT
    )
    gateway = _Gateway()

    _director(gateway).create_directions(
        brief, brief.available_assets, CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    )

    assert gateway.posts[0]["body"]["image_reference_url"] == "https://cdn.example.com/healthy.png"


def test_provenance_never_contains_presigned_urls_credentials_or_the_business_name():
    gateway = _Gateway()
    _, _, [candidate, *_] = _run(
        _director(gateway), [_r2_logo(), _r2_product()], hard_limit=2.0, purpose=AssetPurpose.PRODUCT
    )

    serialized = json.dumps(candidate.generation_metadata) + json.dumps(candidate.provider_metadata)

    for forbidden in ("SECRETSIG", "X-Amz", "r2.cloudflarestorage", "ksecret", "Authorization", "://"):
        assert forbidden not in serialized
    assert "Cositas" not in json.dumps(candidate.generation_metadata)


def test_estimated_units_are_still_labelled_as_an_internal_estimate():
    _, _, [candidate, *_] = _run(_director(_Gateway()), [_r2_logo()], hard_limit=2.0)

    meta = candidate.generation_metadata
    assert meta["credits_used"] == 2.0 == meta["estimated_generation_units"]
    assert meta["credits_are_estimated"] is True and "not_provider" in meta["cost_semantics"]


# --- budget, submissions, errors, fallback ---------------------------------------------


def test_hard_limit_two_still_permits_exactly_one_submission():
    gateway = _Gateway()

    _, budget, candidates = _run(_director(gateway), [_r2_logo()], hard_limit=2.0)

    assert len(gateway.posts) == 1 and len(candidates) == 1
    assert budget.credits_used == 2.0


def test_default_budget_behaviour_is_unchanged_three_explorations():
    gateway = _Gateway()

    _, _, candidates = _run(_director(gateway), [_r2_logo()])

    assert len(gateway.posts) == 3 and len(candidates) == 3
    assert len({c.provider_metadata["angle"] for c in candidates}) == 3


def test_provider_errors_stay_structured_with_a_single_submission_and_no_reroute_retry():
    gateway = _Gateway(fail_with=(403, "not_enough_credits"))

    with pytest.raises(HiggsfieldInsufficientCreditsError):
        _run(_director(gateway), [_r2_logo()])

    assert len(gateway.posts) == 1


def test_an_unknown_configured_model_still_fails_before_any_spend():
    gateway = _Gateway()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    brief = build_creative_brief(business_config=_config())

    with pytest.raises(HiggsfieldApiUnavailableError):
        _director(gateway, "some-invented-model").create_directions(brief, [_r2_logo()], budget)

    assert gateway.posts == [] and budget.credits_used == 0.0


def test_when_no_registered_model_qualifies_the_fallback_is_explicit_and_no_asset_is_forced_through(monkeypatch):
    """Only a reference-required model registered: a HERO cannot be honestly
    generated, so the system falls back — it does NOT push the logo through
    soul/reference just to make generation possible."""
    monkeypatch.setattr(
        director_module, "registered_models", lambda: [m for m in registered_models() if m.model_id == SOUL_REFERENCE]
    )
    gateway = _Gateway()
    fallback = FallbackCreativeDirector(primary=_director(gateway), fallback=InternalCreativeDirector())
    brief = build_creative_brief(business_config=_config())
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    logo = _r2_logo()

    [direction] = fallback.create_directions(brief, [logo], budget)

    assert gateway.posts == []  # nothing submitted to Higgsfield
    assert budget.credits_used == 0.0
    assert direction.provider_metadata["provider"] == "internal_fallback"  # never presented as a Higgsfield image
    assert direction.provider_metadata["fallback_reason"] == "higgsfield_no_suitable_model"
    assert direction.provider_metadata["fallback_detail"] == "no_registered_model_satisfies_requirements"
    assert direction.references == []
    spec = direction.generation_metadata["creative_spec"]
    assert spec["provider"] == "internal" and spec["generated_image"] is False
    assert spec["provider_reference_asset_ids"] == [] and spec["brand_source_asset_ids"] == [str(logo.id)]


def test_an_unsatisfiable_product_request_falls_back_explicitly_too():
    gateway = _Gateway()
    fallback = FallbackCreativeDirector(primary=_director(gateway), fallback=InternalCreativeDirector())
    brief = build_creative_brief(business_config=_config(), purpose=AssetPurpose.PRODUCT)

    [direction] = fallback.create_directions(
        brief, [_r2_logo()], CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    )

    assert gateway.posts == []
    assert direction.provider_metadata["fallback_reason"] == "higgsfield_no_suitable_model"
    assert direction.provider_metadata["fallback_detail"] == "product_reference_missing"


# --- develop ---------------------------------------------------------------------------------


def test_develop_continues_from_the_previous_result_on_a_reference_capable_model_and_keeps_the_purpose():
    gateway = _Gateway()
    director = _director(gateway)
    _, _, [selected, *_] = _run(
        director,
        [_r2_logo()],
        hard_limit=2.0,
        purpose=AssetPurpose.BACKGROUND,
        brand_strategy=BrandStrategy.NEW_DIRECTION,
    )
    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/standard"
    default_brief = build_creative_brief(business_config=_config())  # request-time defaults: HERO

    developed = director.develop_direction(
        selected, default_brief, [], CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    )

    continuation = gateway.posts[-1]
    assert continuation["path"] == "/higgsfield-ai/soul/reference"  # a text-only model can't continue from an image
    assert continuation["body"]["image_reference_url"] == RESULT_URL  # the previous GENERATED image, not the logo
    prompt = continuation["body"]["prompt"].lower()
    assert "no dominant subject" in prompt and "continue the same visual world" in prompt and "cositas" not in prompt
    assert developed.generation_metadata["stage"] == "developed"
    assert developed.generation_metadata["creative_spec"]["purpose"] == "background"


def test_develop_is_skipped_safely_when_no_model_can_continue_from_an_image(monkeypatch):
    gateway = _Gateway()
    director = _director(gateway)
    _, _, [selected, *_] = _run(director, [_r2_logo()], hard_limit=2.0)
    monkeypatch.setattr(
        director_module, "registered_models", lambda: [m for m in registered_models() if m.model_id == SOUL_STANDARD]
    )
    posts_before = len(gateway.posts)

    developed = director.develop_direction(
        selected,
        build_creative_brief(business_config=_config()),
        [],
        CreativeBudget.for_tier(CreativeBudgetTier.STANDARD),
    )

    assert len(gateway.posts) == posts_before  # nothing submitted
    assert developed.generation_metadata["develop_skipped_reason"] == "no_registered_model_satisfies_requirements"


def test_develop_without_a_previous_result_is_skipped():
    gateway = _Gateway()
    director = _director(gateway)
    _, _, [selected, *_] = _run(director, [_r2_logo()], hard_limit=2.0)
    selected.references = []

    developed = director.develop_direction(
        selected,
        build_creative_brief(business_config=_config()),
        [],
        CreativeBudget.for_tier(CreativeBudgetTier.STANDARD),
    )

    assert len(gateway.posts) == 1
    assert developed.generation_metadata["develop_skipped_reason"] == "no_previous_result_to_continue_from"
