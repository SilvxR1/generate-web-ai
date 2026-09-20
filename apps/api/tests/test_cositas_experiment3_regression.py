"""Experiment 3 regression (P2.4) — Cositas y Puntos, HERO + PRESERVE +
PROFESSIONAL.

P2.3 routed correctly (`soul/standard`, no reference, logo as brand source
only) but the prompt still carried the business `description` — "no dispone
de página web", "Instagram", "ecommerce", "catálogo … contacto" — plus an
`ecommerce` industry label and a "website hero" placement. The text-to-image
model drew a webpage mockup: navigation, buttons, headings, a product grid.

These tests pin the semantic fix, not exact prose: operational and digital
context never reaches the image prompt, HERO is a placement for a
standalone picture, and anti-interface rules reach the provider. No real
Higgsfield call, no network: the real HiggsfieldApiClient runs over an
httpx.MockTransport."""

import json
from uuid import UUID

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
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.planning import plan_generation
from app.domain.creative.prompt_composer import compose_prompt
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

# The operational/digital vocabulary that turned Experiment 3 into a mockup.
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
    from uuid import uuid4

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


class _FakeStorage:
    provider_name = "r2"

    def __init__(self) -> None:
        self.keys: list[str] = []

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        self.keys.append(storage_key)
        return PRESIGNED


class _Gateway:
    def __init__(self, *, fail_with: tuple[int, str] | None = None) -> None:
        self.posts: list[dict] = []
        self._fail_with = fail_with

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


# --- CreativeContext and VisualIntent for the Cositas data ------------------------------


def test_operational_and_digital_terms_never_enter_the_creative_context():
    context = plan_generation(_hero_brief(), _cositas_assets()).context

    dumped = context.model_dump_json().lower()

    for term in OPERATIONAL_TERMS:
        assert term not in dumped
    assert context.business_category is None  # `ecommerce` names a business model, not a subject
    assert context.subject_categories == list(SERVICES)  # the verified, structured offerings survive
    assert {item.field for item in context.excluded} >= {"description", "target_customers", "industry"}


def test_cositas_hero_resolves_to_a_conceptual_editorial_intent_not_a_website():
    plan = plan_generation(_hero_brief(), _cositas_assets())

    assert plan.spec.purpose is AssetPurpose.HERO  # placement...
    assert plan.intent.kind.value == "subject_editorial"  # ...separate from what is depicted
    assert plan.intent.grounding.value == "conceptual"  # never presented as real Cositas products
    assert plan.spec.interface_policy.value == "no_interface_depiction"
    assert plan.spec.text_policy.value == "no_generated_text"


# --- the composed prompt ----------------------------------------------------------------------


def _composed():
    brief = _hero_brief()
    plan = plan_generation(brief, _cositas_assets())
    return compose_prompt(
        brief, plan.spec, angle="an angle", profile=plan.profile, context=plan.context, intent=plan.intent
    )


def test_hero_asks_for_a_standalone_asset_placed_later_not_for_a_website():
    composed = _composed()

    assert "standalone visual asset" in " ".join(composed.output_contract).lower()
    placement = " ".join(composed.placement).lower()
    assert "will later be placed inside a website hero section" in placement
    assert "it is not that page" in placement
    interface = " ".join(composed.interface_policy).lower()
    assert "must not depict or simulate a website" in interface and "user interface" in interface


def test_no_generated_text_now_covers_pseudo_text_and_interface_labels_as_instruction_and_negative():
    composed = _composed()
    instructions = " ".join(composed.text_policy).lower()
    negatives = " ".join(composed.negative_constraints).lower()

    assert "pseudo-text" in instructions and "decorative lettering" in instructions  # positive, not only negative
    for required in (
        "no words, letters, numbers or typography",
        "no pseudo-text, decorative lettering or text-like marks",
        "no interface or navigation labels",
        "no signs, labels or packaging containing text",
        "no fake logos",
    ):
        assert required in negatives


def test_the_anti_interface_rules_are_structural_and_cover_the_experiment_3_failures():
    negatives = " ".join(_composed().negative_constraints).lower()

    for required in (
        "no website or webpage",
        "no browser or browser chrome",
        "no navigation bars or menus",
        "no user interface or app interface",
        "no buttons, cards or forms",
        "no screens, dashboards or website mockups",
        "no ecommerce interface or product grid layout",
    ):
        assert required in negatives


def test_operational_words_are_not_visual_instructions_anywhere_in_the_prompt():
    composed = _composed()
    positive_sections = " ".join(
        [
            *composed.visual_intent,
            *composed.creative_context,
            *composed.brand_profile,
            *composed.composition_instructions,
            *composed.subject_truth,
            *composed.text_policy,
            *composed.reference_instructions,
            *composed.output_instructions,
            *composed.output_contract,
        ]
    ).lower()

    for term in OPERATIONAL_TERMS:
        assert term not in positive_sections
    for interface_word in ("navigation", "button", "browser", "menu", "heading", "call-to-action", "grid"):
        assert interface_word not in positive_sections
    whole = to_higgsfield_prompt(composed).lower()
    for term in ("instagram", "carrito", "presencia digital", "catálogo", "portfolio"):
        assert term not in whole  # not even in the negatives: they simply never enter


def test_the_business_name_and_raw_description_are_not_in_the_prompt():
    composed = _composed()
    whole = to_higgsfield_prompt(composed).lower()

    assert "cositas" not in whole and "puntos" not in whole
    assert "pequeña marca" not in whole and "hechos a mano mediante crochet" not in whole
    assert composed.debug["business_name_in_prompt"] is False
    assert composed.debug["raw_business_description_in_prompt"] is False


def test_the_prompt_states_the_subject_is_conceptual_never_a_real_cositas_product():
    truth = " ".join(_composed().subject_truth).lower()
    assert "conceptual and representational" in truth
    assert "must not be presented as, or imply, a real product" in truth


# --- the provider request -----------------------------------------------------------------------


def test_cositas_hero_still_routes_to_soul_standard_and_sends_no_reference_or_logo():
    gateway, storage = _Gateway(), _FakeStorage()

    _, _, [candidate, *_] = _run(_director(gateway, storage))

    [post] = gateway.posts
    body = post["body"]
    assert post["path"] == "/higgsfield-ai/soul/standard"
    assert sorted(body) == ["aspect_ratio", "prompt"]
    assert body["aspect_ratio"] == "16:9"
    assert storage.keys == []  # no presigned URL was ever minted
    serialized = json.dumps(body)
    assert str(LOGO_ID) not in serialized and "SECRETSIG" not in serialized and "cloudflarestorage" not in serialized
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["brand_source_asset_ids"] == [str(LOGO_ID)]  # the logo is a brand source only
    assert spec["provider_reference_asset_ids"] == []
    assert spec["model_selection"]["selected"] == SOUL_STANDARD


def test_anti_interface_rules_and_the_standalone_contract_reach_the_provider_prompt():
    gateway = _Gateway()

    _run(_director(gateway))

    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "standalone visual asset" in prompt
    assert "will later be placed inside a website hero section" in prompt
    assert "no website or webpage" in prompt and "no browser or browser chrome" in prompt
    assert "no pseudo-text" in prompt and "no ecommerce interface" in prompt
    assert "cositas" not in prompt and "instagram" not in prompt


def test_the_three_explorations_are_subject_variations_not_website_concepts():
    gateway = _Gateway()

    _, _, candidates = _run(_director(gateway), hard_limit=None)

    prompts = [post["body"]["prompt"].lower() for post in gateway.posts]
    assert len(prompts) == 3 and len(set(prompts)) == 3
    assert len({c.provider_metadata["angle"] for c in candidates}) == 3
    for prompt in prompts:
        assert "represents these verified subject categories" in prompt
        intent_section = prompt.split("visual intent:")[1].split("verified creative context:")[0]
        for interface_word in ("navigation", "website", "webpage", "button", "menu", "browser"):
            assert interface_word not in intent_section  # what to depict never mentions interfaces


# --- provenance ------------------------------------------------------------------------------------


def test_provenance_explains_why_this_kind_of_visual_without_raw_business_text():
    gateway = _Gateway()

    _, _, [candidate, *_] = _run(_director(gateway))

    spec = candidate.generation_metadata["creative_spec"]
    assert spec["purpose"] == "hero"
    assert spec["visual_intent"] == "subject_editorial"
    assert spec["visual_intent_reason"] == "verified_subject_categories_available"
    assert spec["subject_grounding"] == "conceptual"
    assert spec["interface_policy"] == "no_interface_depiction"
    context = spec["creative_context"]
    assert context["version"] and context["included_fields"] == ["services"]
    assert context["subject_category_count"] == 4
    excluded = {(item["field"], item["reason"]) for item in context["excluded"]}
    assert ("description", "free_text_may_carry_operational_or_digital_context") in excluded
    assert ("target_customers", "free_text_may_carry_operational_or_digital_context") in excluded
    assert ("industry", "not_a_visual_subject") in excluded
    serialized = json.dumps(candidate.generation_metadata) + json.dumps(candidate.provider_metadata)
    for forbidden in ("Instagram", "página web", "ecommerce", "Amigurumis", "SECRETSIG", "X-Amz", "ksecret", "://"):
        assert forbidden not in serialized  # ids, field names and reason codes only
    assert spec["prompt_version"] == "p2.4-v1" and spec["prompt_fingerprint"]


# --- P2.3 behaviour that must not regress --------------------------------------------------------------


def test_hard_limit_two_still_permits_exactly_one_submission_and_never_retries():
    gateway = _Gateway()
    _, budget, candidates = _run(_director(gateway))
    assert len(gateway.posts) == 1 and len(candidates) == 1 and budget.credits_used == 2.0

    failing = _Gateway(fail_with=(403, "not_enough_credits"))
    with pytest.raises(HiggsfieldInsufficientCreditsError):
        _run(_director(failing))
    assert len(failing.posts) == 1


def test_soul_reference_still_serves_a_legitimate_reference_conditioned_product_request():
    gateway, storage = _Gateway(), _FakeStorage()
    product = _asset(AssetKind.IMAGE, AssetCategory.PRODUCT, url="https://pub.example/p.png", r2_key="biz/p.png")
    brief = build_creative_brief(business_config=_cositas_config(), purpose=AssetPurpose.PRODUCT)

    _, _, [candidate, *_] = _run(_director(gateway, storage), brief=brief, assets=[*_cositas_assets(), product])

    [post] = gateway.posts
    assert post["path"] == "/higgsfield-ai/soul/reference"
    assert post["body"]["image_reference_url"] == PRESIGNED
    assert storage.keys == ["biz/p.png"]  # only the real product was signed, never the logo
    spec = candidate.generation_metadata["creative_spec"]
    assert spec["visual_intent"] == "product_grounded" and spec["subject_grounding"] == "grounded"
    assert spec["provider_reference_asset_ids"] == [str(product.id)]


def test_product_still_requires_a_real_product_image_and_never_invents_one():
    gateway = _Gateway()
    brief = build_creative_brief(business_config=_cositas_config(), purpose=AssetPurpose.PRODUCT)

    with pytest.raises(HiggsfieldNoSuitableModelError) as excinfo:
        _run(_director(gateway), brief=brief)

    assert excinfo.value.reason_code == "product_reference_missing"
    assert gateway.posts == []


def test_fallback_is_still_explicit_and_carries_the_same_intent_without_a_generated_image(monkeypatch):
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
    assert spec["visual_intent"] == "subject_editorial" and spec["subject_grounding"] == "conceptual"


def test_develop_keeps_the_recorded_visual_intent_of_the_direction_it_deepens():
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
    assert continuation["path"] == "/higgsfield-ai/soul/reference"  # continues from the previous generated image
    prompt = continuation["body"]["prompt"].lower()
    assert "represents these verified subject categories" in prompt and "continue the same world" in prompt
    assert "cositas" not in prompt and "instagram" not in prompt
