"""Cositas y Puntos regression (P2.5) — HERO + PRESERVE + PROFESSIONAL,
covering Experiments 3 and 4.

Experiment 3 (P2.3): correct routing, but the raw business description
reached the prompt and the model drew a webpage.
Experiment 4 (P2.4): operational context was removed, yet the model still
drew a page-like layout with pseudo-text — the prompt listed all four verified
offerings (their labels even appeared as text in the image), explained our
"website hero" placement and repeated long interface vocabularies. The image
model still had to invent the subject, scene and layout.

P2.5 fixes the gap between VisualIntent and the prompt: ONE narrow subject, a
concrete deterministic scene plan, and a GenerationContract validated before
any spend. These tests pin structured semantics first, then key properties of
the provider prompt — never one exact prompt string. No real Higgsfield call,
no network: the real HiggsfieldApiClient runs over an httpx.MockTransport."""

import json
import re
from uuid import UUID, uuid4

import httpx
import pytest

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield import director as director_module
from app.creative.higgsfield.api_client import (
    HiggsfieldApiClient,
    HiggsfieldInsufficientCreditsError,
    HiggsfieldNoSuitableModelError,
    registered_models,
)
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.creative.higgsfield.translation import to_higgsfield_prompt
from app.domain.business_config import BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.creative import planning as planning_module
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.generation_contract import validate_generation_contract
from app.domain.creative.planning import plan_generation
from app.domain.creative.prompt_composer import compose_prompt
from app.domain.creative.scene_plan import SubjectSide
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

LOGO_ID = UUID("0ecf3acd-2757-4c78-bc95-b841298ccedf")
SOUL_REFERENCE = "higgsfield-ai/soul/reference"
SOUL_STANDARD = "higgsfield-ai/soul/standard"
PRESIGNED = "https://acct.r2.cloudflarestorage.com/biz/x.png?X-Amz-Signature=SECRETSIG"

OPERATIONAL_TERMS = (
    "instagram",
    "ecommerce",
    "página web",
    "pagina web",
    "catálogo",
    "catalogo",
    "portfolio",
    "carrito",
    "redes sociales",
    "presencia digital",
    "prioridad móvil",
)

DESCRIPTION = (
    "Pequeña marca artesanal española especializada en la creación de amigurumis hechos a mano mediante crochet. "
    "Actualmente no dispone de página web; su principal presencia online es Instagram, donde publica fotografías "
    "reales de sus trabajos. El objetivo es crear una presencia digital profesional en formato catálogo/portfolio "
    "+ contacto/encargo (sin ecommerce, carrito ni pago online en esta primera versión)."
)
TARGET = (
    "Principalmente personas que buscan amigurumis, regalos artesanales o personalizados. Se espera que una parte "
    "importante de los visitantes llegue desde Instagram y redes sociales (prioridad móvil)."
)
SERVICES = ("Amigurumis artesanales hechos a mano", "Llaveros de lana", "Tartas de pañales", "Cestas personalizadas")
# Distinctive fragments of the four service labels — none may appear in the prompt.
SERVICE_FRAGMENTS = ("amigurumis artesanales", "llaveros", "tartas de pa", "cestas personalizadas")


def _cositas_config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.ECOMMERCE,
            description=DESCRIPTION,
            target_customers=TARGET,
            services=[
                ServiceOffering(id=f"svc-{i}", name=name, description="Descripción.")
                for i, name in enumerate(SERVICES, start=1)
            ],
        )
    )


def _asset(kind, category, *, id=None, url="https://cdn.example.com/a.png", r2_key=None) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=id or uuid4(),
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        url=url,
        storage_provider="r2" if r2_key else None,
        storage_key=r2_key,
    )


def _cositas_assets() -> list[CreativeBriefAsset]:
    """The real production shape: one R2-backed official logo plus four legacy
    gallery photos on non-https URLs."""
    logo = _asset(
        AssetKind.LOGO, AssetCategory.LOGO, id=LOGO_ID, url="https://pub.example/logo.jpg", r2_key="biz/logo.jpg"
    )
    gallery = [_asset(AssetKind.IMAGE, AssetCategory.GALLERY, url=f"http://legacy.example/{n}.jpeg") for n in range(4)]
    return [*gallery, logo]


def _hero_brief(**kwargs):
    return build_creative_brief(
        business_config=_cositas_config(),
        purpose=AssetPurpose.HERO,
        brand_strategy=BrandStrategy.PRESERVE,
        creative_level=CreativeLevel.PROFESSIONAL,
        **kwargs,
    )


def _plan():
    return plan_generation(_hero_brief(), _cositas_assets())


class _FakeStorage:
    provider_name = "r2"

    def __init__(self) -> None:
        self.keys: list[str] = []

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        self.keys.append(storage_key)
        return PRESIGNED


class _Gateway:
    def __init__(self, *, fail_with: tuple[int, str] | None = None, events: list[str] | None = None) -> None:
        self.posts: list[dict] = []
        self._fail_with = fail_with
        self._events = events

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if self._events is not None:
                self._events.append("provider_post")
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
        return httpx.Response(200, json={"status": "completed", "images": [{"url": "https://cdn.example.com/out.png"}]})


def _director(gateway: _Gateway, storage: _FakeStorage | None = None) -> HiggsfieldApiCreativeDirector:
    http_client = httpx.Client(transport=httpx.MockTransport(gateway), base_url="https://api.higgsfield.ai")
    client = HiggsfieldApiClient(key_id="kid", key_secret="ksecret", http_client=http_client)
    return HiggsfieldApiCreativeDirector(client, job_type=SOUL_REFERENCE, storage=storage or _FakeStorage())


def _run(director, *, hard_limit: float | None = 2.0, brief=None, assets=None):
    brief = brief or _hero_brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=hard_limit)
    candidates = director.create_directions(brief, assets if assets is not None else _cositas_assets(), budget)
    return brief, budget, candidates


def _positive(text: str) -> str:
    """The provider prompt without its final prohibitions."""
    return text.lower().split("\nno ")[0]


# --- structured decisions ------------------------------------------------------------------------


def test_purpose_intent_and_grounding_are_unchanged_from_p2_4():
    plan = _plan()

    assert plan.spec.purpose is AssetPurpose.HERO
    assert plan.intent.kind.value == "subject_editorial"
    assert plan.intent.grounding.value == "conceptual"  # never presented as real Cositas products
    assert plan.spec.text_policy.value == "no_generated_text"
    assert plan.spec.interface_policy.value == "no_interface_depiction"


def test_a_single_narrow_subject_is_selected_from_the_verified_offerings():
    plan = _plan()

    assert plan.context.subject_categories == list(SERVICES)  # all four verified...
    assert plan.subject.label == "crochet and yarn craft"  # ...one narrow visual subject chosen
    assert plan.subject.source.value == "material_family_from_verified_labels"
    assert plan.subject.grounding.value == "conceptual"
    assert plan.subject.considered_categories == 4


def test_the_scene_plan_is_single_scene_with_a_clear_subject_negative_space_and_16_9():
    scene = _plan().scenes[0]

    assert scene.primary_subject == "crochet and yarn craft materials"
    assert "single continuous scene" in scene.composition.lower() and "not a collage" in scene.composition.lower()
    assert scene.subject_side is SubjectSide.RIGHT
    assert "negative space" in scene.negative_space.lower() and "left" in scene.negative_space.lower()
    assert scene.aspect_ratio == "16:9"
    assert scene.grounding.value == "conceptual" and scene.requires_fidelity is False
    for invite_ui_or_text in ("collage", "grid", "packaging", "shelves or storefront"):
        assert invite_ui_or_text in scene.forbidden_elements


def test_the_scene_does_not_request_ui_text_a_website_a_catalog_or_real_inventory():
    scene = _plan().scenes[0]
    described = " ".join(
        value
        for value in scene.model_dump(mode="json", exclude={"forbidden_elements"}).values()
        if isinstance(value, str)
    ).lower()

    for term in ("website", "webpage", "browser", "screen", "interface", "navigation", "button", "menu", "ecommerce"):
        assert term not in described
    for term in ("text", "lettering", "caption", "heading", "typography", "logo", "label", "sign"):
        assert not re.search(rf"\b{term}s?\b", described)  # whole words only: "textile" and "texture" are fine
    for term in ("catalog", "catálogo", "shop", "store", "product grid"):
        assert term not in described
    assert "no identifiable finished products" in described  # never implies real Cositas inventory


def test_the_contract_is_built_before_provider_execution_and_validates():
    plan = _plan()

    assert plan.contract.purpose is AssetPurpose.HERO
    assert plan.contract.subject == plan.subject and plan.contract.scene == plan.scenes[0]
    assert plan.contract.provider_references == () and plan.contract.requires_visual_reference is False
    for variant in range(len(plan.scenes)):
        assert validate_generation_contract(plan.contract_for(variant)) == []


# --- the provider prompt ---------------------------------------------------------------------------


def test_the_provider_prompt_is_concrete_visual_instructions_derived_from_the_scene_plan():
    plan = _plan()
    text = to_higgsfield_prompt(compose_prompt(plan.contract)).lower()

    for concrete in (
        plan.scenes[0].medium.lower(),
        "crochet and yarn craft materials",
        "single continuous scene",
        "subject concentrated toward the right half",
        "negative space on the left",
        "wide 16:9",
        "soft natural studio light",
        "tactile textile detail",
    ):
        assert concrete in text


def test_the_scene_does_not_ask_the_model_to_depict_all_four_offerings():
    text = to_higgsfield_prompt(compose_prompt(_plan().contract)).lower()

    for fragment in SERVICE_FRAGMENTS:
        assert fragment not in text  # the labels never reach the prompt, so they cannot be rendered as text either


def test_provider_prompt_has_no_positive_website_or_ecommerce_semantics():
    positive = _positive(to_higgsfield_prompt(compose_prompt(_plan().contract)))

    for term in ("website", "webpage", "web page", "browser", "ecommerce", "page layout", "hero", "user interface"):
        assert term not in positive  # placement was translated into composition


def test_provider_prompt_has_no_business_name_description_or_target_customer():
    text = to_higgsfield_prompt(compose_prompt(_plan().contract)).lower()

    assert "cositas" not in text and "puntos" not in text
    for term in OPERATIONAL_TERMS:
        assert term not in text
    for fragment in ("pequeña marca", "hechos a mano mediante", "regalos artesanales", "visitantes"):
        assert fragment not in text


def test_the_prompt_is_far_smaller_than_p2_4s_without_losing_the_key_constraints():
    text = to_higgsfield_prompt(compose_prompt(_plan().contract))

    assert len(text) < 1200  # P2.4's prompt for the same request was ≈3,470 characters
    lowered = text.lower()
    for constraint in (
        "no text, lettering, pseudo-text",
        "no interface elements, browser, navigation",
        "no collage, grid",
    ):
        assert constraint in lowered


# --- the provider request --------------------------------------------------------------------------


def test_the_logo_stays_a_brand_source_and_nothing_visual_reaches_the_provider():
    gateway, storage = _Gateway(), _FakeStorage()

    _, _, [candidate, *_] = _run(_director(gateway, storage))

    [post] = gateway.posts
    body = post["body"]
    assert post["path"] == "/higgsfield-ai/soul/standard"  # selected by capability, not by configuration
    assert sorted(body) == ["aspect_ratio", "prompt"] and body["aspect_ratio"] == "16:9"
    assert storage.keys == []  # no presigned URL was minted
    serialized = json.dumps(body)
    assert str(LOGO_ID) not in serialized and "SECRETSIG" not in serialized and "cloudflarestorage" not in serialized
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["brand_source_asset_ids"] == [str(LOGO_ID)] and spec["provider_reference_asset_ids"] == []
    assert spec["model_selection"]["selected"] == SOUL_STANDARD
    assert spec["model_selection"]["reason"].startswith("configured_model_unsuitable:requires_a_reference")


def test_the_contract_is_validated_before_the_first_provider_submission(monkeypatch):
    events: list[str] = []
    real = director_module.assert_valid_generation_contract

    def spy(contract, **kwargs):
        events.append("contract_validated")
        return real(contract, **kwargs)

    monkeypatch.setattr(director_module, "assert_valid_generation_contract", spy)

    _run(_director(_Gateway(events=events)))

    assert events[0] == "contract_validated"
    assert events.index("contract_validated") < events.index("provider_post")


def test_an_invalid_contract_fails_before_any_provider_call_or_spend(monkeypatch):
    real_plan_scenes = planning_module.plan_scenes

    def scenes_asking_for_a_webpage(**kwargs):
        return tuple(
            scene.model_copy(update={"primary_subject": "a website landing page"})
            for scene in real_plan_scenes(**kwargs)
        )

    monkeypatch.setattr(planning_module, "plan_scenes", scenes_asking_for_a_webpage)
    gateway = _Gateway()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)

    with pytest.raises(HiggsfieldNoSuitableModelError) as excinfo:
        _director(gateway).create_directions(_hero_brief(), _cositas_assets(), budget)

    assert excinfo.value.reason_code == "scene_requests_interface"
    assert gateway.posts == [] and budget.credits_used == 0.0


# --- provenance --------------------------------------------------------------------------------------


def test_provenance_records_subject_scene_and_contract_without_secrets_or_raw_text():
    _, _, [candidate, *_] = _run(_director(_Gateway()))

    spec = candidate.generation_metadata["creative_spec"]
    assert spec["purpose"] == "hero" and spec["visual_intent"] == "subject_editorial"
    assert spec["subject_grounding"] == "conceptual"
    assert spec["visual_subject"] == "crochet and yarn craft"
    assert spec["visual_subject_source"] == "material_family_from_verified_labels"
    assert spec["scene_plan_version"] == "p2.5-v1" and spec["generation_contract_version"] == "p2.5-v1"
    assert spec["scene_plan"]["subject_side"] == "right" and spec["scene_plan"]["aspect_ratio"] == "16:9"
    assert spec["scene_plan"]["primary_subject"] == "crochet and yarn craft materials"
    assert spec["prompt_version"] == "p2.5-v1" and spec["prompt_fingerprint"]
    serialized = json.dumps(candidate.generation_metadata) + json.dumps(candidate.provider_metadata)
    for forbidden in (
        "Instagram",
        "página web",
        "ecommerce",
        "Llaveros",
        "Tartas",
        "SECRETSIG",
        "X-Amz",
        "ksecret",
        "://",
    ):
        assert forbidden not in serialized


def test_the_three_explorations_are_deterministic_scene_variants_of_one_subject():
    gateway = _Gateway()

    _, _, candidates = _run(_director(gateway), hard_limit=None)

    prompts = [post["body"]["prompt"] for post in gateway.posts]
    assert len(prompts) == 3 and len(set(prompts)) == 3
    assert len({c.generation_metadata["creative_spec"]["scene_plan"]["primary_subject"] for c in candidates}) == 1
    assert [c.generation_metadata["creative_spec"]["scene_plan"]["subject_side"] for c in candidates] == [
        "right",
        "left",
        "right",
    ]


# --- P2.3 / P2.4 behaviour that must not regress ------------------------------------------------------------


def test_hard_limit_two_still_permits_exactly_one_submission_and_never_retries():
    gateway = _Gateway()
    _, budget, candidates = _run(_director(gateway))
    assert len(gateway.posts) == 1 and len(candidates) == 1 and budget.credits_used == 2.0

    failing = _Gateway(fail_with=(403, "not_enough_credits"))
    with pytest.raises(HiggsfieldInsufficientCreditsError):
        _run(_director(failing))
    assert len(failing.posts) == 1


def test_soul_reference_still_serves_a_grounded_product_request_and_only_signs_the_product():
    gateway, storage = _Gateway(), _FakeStorage()
    product = _asset(AssetKind.IMAGE, AssetCategory.PRODUCT, url="https://pub.example/p.png", r2_key="biz/p.png")
    brief = build_creative_brief(business_config=_cositas_config(), purpose=AssetPurpose.PRODUCT)

    _, _, [candidate, *_] = _run(_director(gateway, storage), brief=brief, assets=[*_cositas_assets(), product])

    [post] = gateway.posts
    assert post["path"] == "/higgsfield-ai/soul/reference" and post["body"]["image_reference_url"] == PRESIGNED
    assert storage.keys == ["biz/p.png"]
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["visual_intent"] == "product_grounded" and spec["subject_grounding"] == "grounded"
    assert spec["visual_subject_source"] == "grounded_reference" and spec["scene_plan"]["requires_fidelity"] is True
    assert spec["provider_reference_asset_ids"] == [str(product.id)]


def test_product_still_requires_a_real_product_image_and_never_invents_one():
    gateway = _Gateway()
    brief = build_creative_brief(business_config=_cositas_config(), purpose=AssetPurpose.PRODUCT)

    with pytest.raises(HiggsfieldNoSuitableModelError) as excinfo:
        _run(_director(gateway), brief=brief)

    assert excinfo.value.reason_code == "product_reference_missing"
    assert gateway.posts == []


def test_fallback_is_still_explicit_and_the_internal_result_carries_the_same_subject_and_scene(monkeypatch):
    monkeypatch.setattr(
        director_module, "registered_models", lambda: [m for m in registered_models() if m.model_id == SOUL_REFERENCE]
    )
    gateway = _Gateway()
    fallback = FallbackCreativeDirector(primary=_director(gateway), fallback=InternalCreativeDirector())

    [direction] = fallback.create_directions(
        _hero_brief(), _cositas_assets(), CreativeBudget.for_tier(CreativeBudgetTier.STANDARD, hard_limit=2.0)
    )

    assert gateway.posts == []
    assert direction.provider_metadata["provider"] == "internal_fallback"
    assert direction.provider_metadata["fallback_reason"] == "higgsfield_no_suitable_model"
    spec = direction.generation_metadata["creative_spec"]
    assert spec["generated_image"] is False and spec["provider_reference_asset_ids"] == []
    assert spec["visual_subject"] == "crochet and yarn craft" and spec["scene_plan"]["subject_side"] == "right"


def test_develop_continues_the_same_subject_from_the_previous_image():
    gateway = _Gateway()
    director = _director(gateway)
    _, _, [selected, *_] = _run(director)

    director.develop_direction(
        selected,
        build_creative_brief(business_config=_cositas_config()),
        [],
        CreativeBudget.for_tier(CreativeBudgetTier.STANDARD),
    )

    continuation = gateway.posts[-1]
    prompt = continuation["body"]["prompt"].lower()
    assert continuation["path"] == "/higgsfield-ai/soul/reference"
    assert continuation["body"]["image_reference_url"] == "https://cdn.example.com/out.png"
    assert prompt.startswith("continue the same visual world as the reference image")
    assert "crochet and yarn craft materials" in prompt
    assert "cositas" not in prompt and "instagram" not in prompt
