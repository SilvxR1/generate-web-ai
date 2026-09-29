"""v0.2 R1 — BUSINESS TRUTH.

BusinessTruth defines what the platform knows; it does not define how the
website should look. These tests prove it is deterministic, provider-free,
presentation-free and secret-free; that it preserves real assets, logo,
reviews, legal and contact facts with provenance and never fabricates any;
and that the generative engine's factual input and legal pages come from it.

Synthetic fixtures only. No network, no Anthropic, no Higgsfield.
"""

import json
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.manifest import GeneratedProjectManifest
from app.creative.frontend_engine.prompts import build_system_prompt, build_user_message
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.brand import AssetRef, BrandColors, BrandConfig, BrandTypography
from app.domain.business_config.business_profile import (
    BusinessHoursRule,
    ContactInfo,
    Location,
    PostalAddress,
    ServiceOffering,
)
from app.domain.business_config.legal import LegalProfile
from app.domain.business_config.whatsapp import WhatsAppConfig
from app.domain.business_truth import BusinessTruth, FactSource, derive_business_truth
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BusinessVertical, ReviewSource, Weekday


@dataclass
class _Asset:
    id: uuid.UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    url: str
    alt_text: str | None = None


@dataclass
class _Review:
    id: uuid.UUID
    source: ReviewSource
    body: str
    source_review_id: str | None = None
    author_name: str | None = None
    rating: int | None = None
    review_url: str | None = None
    published_at: datetime | None = None
    is_visible: bool = True


LOGO_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
PHOTO_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")
GEN_ID = uuid.UUID("00000000-0000-0000-0000-00000000000c")
GEN_LOGO_ID = uuid.UUID("00000000-0000-0000-0000-00000000000d")


def _config(**overrides) -> BusinessConfig:
    profile = dict(
        name="Nexo Reformas",
        slug="nexo-reformas",
        industry=BusinessVertical.HOME_RENOVATION,
        description="Reformas integrales en Valencia.",
        target_customers="Propietarios de vivienda",
        location=Location(city="Valencia", region="Valencia", country="ES", postal_code="46001"),
        service_area=["Valencia", "Paterna"],
        services=[
            ServiceOffering(id="cocinas", name="Cocinas", description="Reforma de cocinas."),
            ServiceOffering(
                id="banos", name="Baños", description="Reforma de baños.", price_from=3000, price_unit="EUR"
            ),
        ],
        contact=ContactInfo(email="hola@nexo.example", phone="+34 600 000 000"),
        business_hours=[BusinessHoursRule(days=[Weekday.MONDAY, Weekday.TUESDAY], opens="09:00", closes="18:00")],
    )
    profile.update(overrides.pop("profile", {}))
    return BusinessConfig(business_profile=BusinessProfile(**profile), **overrides)


def _brand(**overrides) -> BrandConfig:
    return BrandConfig(
        colors=BrandColors(primary="#111", secondary="#222", accent="#333", background="#fff", foreground="#000"),
        typography=BrandTypography(sans="Inter"),
        **overrides,
    )


def _assets() -> list[_Asset]:
    return [
        _Asset(
            GEN_ID, AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE, AssetOrigin.GENERATED, "https://cdn.example/gen.jpg"
        ),
        _Asset(
            PHOTO_ID, AssetKind.IMAGE, AssetCategory.PROJECT, AssetOrigin.UPLOADED, "https://cdn.example/obra.jpg",
            "Obra",
        ),
        _Asset(
            LOGO_ID, AssetKind.LOGO, AssetCategory.LOGO, AssetOrigin.UPLOADED, "https://cdn.example/logo.png", "Logo"
        ),
    ]


def _direction() -> CreativeDirection:
    return CreativeDirection(
        concept=CreativeConcept(name="n", rationale="r", narrative="n"),
        visual_language=VisualLanguage(
            mood="m",
            palette_direction="p",
            typography_direction="t",
            composition_philosophy="c",
            imagery_treatment="i",
            graphic_language="g",
        ),
        experience=ExperienceDirection(navigation_concept="n", storytelling_model="s", responsive_adaptation="r"),
        content_strategy=ContentStrategy(hierarchy="h", primary_user_journey="j", conversion_strategy="c"),
    )


@pytest.fixture(autouse=True)
def _no_network_no_providers(monkeypatch: pytest.MonkeyPatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("BusinessTruth must never touch the network or a provider")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr("app.creative.higgsfield.director._HiggsfieldDirectorBase.create_directions", _refuse)


# --- Determinism, provider independence, no presentation, no secrets ------------


def test_same_stored_business_gives_identical_truth_regardless_of_row_order():
    reviews = [
        _Review(uuid.uuid4(), ReviewSource.MANUAL, "Muy bien", published_at=datetime(2026, 1, 2, tzinfo=UTC)),
        _Review(uuid.uuid4(), ReviewSource.GOOGLE, "Genial", published_at=datetime(2026, 1, 1, tzinfo=UTC)),
    ]
    first = derive_business_truth(business_config=_config(), assets=_assets(), reviews=reviews)
    second = derive_business_truth(
        business_config=_config(), assets=list(reversed(_assets())), reviews=reviews[::-1]
    )
    assert first == second
    assert first.canonical_json() == second.canonical_json()


def test_no_layout_or_presentation_fields_leak_into_truth():
    truth = derive_business_truth(
        business_config=_config(brand=_brand(visual_style="bold", tagline="Tu casa")), assets=_assets()
    )
    keys: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(truth.canonical_json()))
    forbidden = {
        "theme", "colors", "typography", "visual_style", "layout", "hero", "section", "sections", "gallery",
        "spacing", "radius", "density", "featured", "font", "fonts", "variant", "blocks", "pages",
    }
    assert not (keys & forbidden), keys & forbidden


def test_serialized_truth_carries_no_secrets_or_private_storage_identifiers():
    text = derive_business_truth(business_config=_config(), assets=_assets()).canonical_json().lower()
    for leak in (
        "storage_key", "storage_provider", "presigned", "x-amz", "password", "secret", "api_key",
        "token", "database_url", "tenant",
    ):
        assert leak not in text, leak


# --- Assets and logo ----------------------------------------------------------


def test_real_logo_is_preserved_by_stable_asset_identity():
    truth = derive_business_truth(business_config=_config(), assets=_assets())
    assert truth.logo is not None
    assert truth.logo.asset_id == LOGO_ID
    assert truth.logo.url == "https://cdn.example/logo.png"
    assert truth.logo.source is FactSource.OWNER_PROVIDED


def test_missing_logo_stays_absent_and_a_generated_logo_is_never_the_logo():
    generated_logo = _Asset(
        GEN_LOGO_ID, AssetKind.LOGO, AssetCategory.LOGO, AssetOrigin.GENERATED, "https://cdn.example/g.png"
    )
    truth = derive_business_truth(business_config=_config(), assets=[generated_logo])
    assert truth.logo is None  # no real logo → absent, never fabricated
    [asset] = truth.assets
    assert asset.is_real is False and asset.origin is AssetOrigin.GENERATED


def test_owner_entered_brand_logo_is_used_only_without_a_real_logo_asset():
    brand = _brand(logo=AssetRef(url="https://cdn.example/brand-logo.svg", alt="Nexo"))
    truth = derive_business_truth(business_config=_config(brand=brand), assets=[])
    assert truth.logo is not None and truth.logo.url.endswith("brand-logo.svg") and truth.logo.asset_id is None
    with_asset = derive_business_truth(business_config=_config(brand=brand), assets=_assets())
    assert with_asset.logo is not None and with_asset.logo.asset_id == LOGO_ID


def test_generated_assets_are_distinguishable_and_real_photos_keep_provenance():
    truth = derive_business_truth(business_config=_config(), assets=_assets())
    by_id = {asset.id: asset for asset in truth.assets}
    assert by_id[PHOTO_ID].is_real and by_id[PHOTO_ID].origin is AssetOrigin.UPLOADED
    assert by_id[PHOTO_ID].category is AssetCategory.PROJECT and by_id[PHOTO_ID].alt_text == "Obra"
    assert by_id[GEN_ID].is_real is False and by_id[GEN_ID].origin is AssetOrigin.GENERATED
    assert [a.id for a in truth.real_assets] == [LOGO_ID, PHOTO_ID]
    assert truth.assets[-1].id == GEN_ID  # real content first


# --- Reviews --------------------------------------------------------------------


def test_missing_reviews_produce_an_empty_collection():
    assert derive_business_truth(business_config=_config()).reviews == []


def test_real_reviews_preserve_source_and_nothing_is_synthesized():
    reviews = [
        _Review(
            uuid.uuid4(), ReviewSource.GOOGLE, " Excelente ", source_review_id="g-1", rating=5,
            review_url="https://maps.example/r/1", published_at=datetime(2026, 2, 1, tzinfo=UTC),
        ),
        _Review(uuid.uuid4(), ReviewSource.MANUAL, "Recomendable", rating=9),  # out-of-range rating is dropped
        _Review(uuid.uuid4(), ReviewSource.GOOGLE, "Oculta", is_visible=False),
    ]
    truth = derive_business_truth(business_config=_config(), reviews=reviews)

    assert len(truth.reviews) == 2  # hidden review excluded
    google = next(r for r in truth.reviews if r.source is ReviewSource.GOOGLE)
    assert google.provenance is FactSource.EXTERNAL_IMPORTED and google.source_review_id == "g-1"
    assert google.body == "Excelente" and google.rating == 5
    assert google.author_name is None  # never invented
    manual = next(r for r in truth.reviews if r.source is ReviewSource.MANUAL)
    assert manual.provenance is FactSource.OWNER_PROVIDED and manual.rating is None


# --- Legal, contact, services, claims ------------------------------------------


def test_legal_name_and_registered_address_are_preserved_when_stored():
    legal = LegalProfile(
        legal_name="Nexo Reformas S.L.",
        registration_number="B12345678",
        address=PostalAddress(street_address="Calle Mayor 1", locality="Valencia", postal_code="46001", country="ES"),
        privacy_contact_email="privacidad@nexo.example",
    )
    truth = derive_business_truth(business_config=_config(legal_profile=legal))
    assert truth.legal.legal_name == "Nexo Reformas S.L."
    assert truth.legal.registered_address is not None
    assert truth.legal.registered_address.street_address == "Calle Mayor 1"
    assert truth.legal.privacy_contact_email == "privacidad@nexo.example"


def test_missing_legal_data_stays_missing_never_substituted():
    truth = derive_business_truth(business_config=_config())
    assert truth.legal.legal_name is None  # not the trading name
    assert truth.legal.registered_address is None
    assert truth.legal.tax_id is None


def test_contact_email_and_phone_are_preserved_and_whatsapp_is_only_present_when_authoritative():
    truth = derive_business_truth(business_config=_config())
    assert truth.contact.email == "hola@nexo.example"
    assert truth.contact.phone == "+34 600 000 000"
    assert truth.contact.whatsapp is None  # a phone number alone never implies WhatsApp

    disabled = derive_business_truth(
        business_config=_config(whatsapp=WhatsAppConfig(enabled=False, phone_number="+34 611 111 111"))
    )
    assert disabled.contact.whatsapp is None

    enabled = derive_business_truth(
        business_config=_config(whatsapp=WhatsAppConfig(enabled=True, phone_number="+34 611 111 111"))
    )
    assert enabled.contact.whatsapp is not None
    assert enabled.contact.whatsapp.phone_number == "+34 611 111 111"


def test_services_are_preserved_in_owner_order():
    truth = derive_business_truth(business_config=_config())
    assert [(s.id, s.name, s.price_from) for s in truth.services] == [
        ("cocinas", "Cocinas", None),
        ("banos", "Baños", 3000),
    ]


def test_unsupported_claims_are_never_introduced():
    config = _config(brand=_brand(tagline="Más de 500 reformas desde 1998"))
    truth = derive_business_truth(business_config=config)
    assert truth.claims.supported == []  # no structured claim exists to state
    assert truth.identity.tagline == "Más de 500 reformas desde 1998"  # owner prose, flagged as unverified
    assert "identity.tagline" in truth.claims.unverified_free_text_fields


# --- Generative engine consumes BusinessTruth ----------------------------------


def test_generative_prompt_carries_business_truth_and_no_fabrication_rules():
    truth = derive_business_truth(business_config=_config(), assets=_assets())
    message = build_user_message(business_truth=truth, creative_direction=_direction())
    assert "BUSINESS TRUTH" in message
    assert truth.canonical_json() in message  # the exact deterministic serialization
    system = build_system_prompt()
    for rule in ("Never invent reviews", "Missing information stays missing", "`logo` is null", "is_real: false"):
        assert rule in system, rule


def test_engine_builds_its_prompt_and_legal_pages_from_business_truth(tmp_path):
    from app.creative.frontend_engine.anthropic_engine import AnthropicFrontendEngine
    from app.storage import LocalStorageProvider

    captured: dict = {}

    class _Client:
        def generate_manifest(self, *, system: str, user_content: str) -> GeneratedProjectManifest:
            captured["user"] = user_content
            raise RuntimeError("stop after prompt construction")  # no build, no provider

    legal = LegalProfile(legal_name="Nexo Reformas S.L.")
    truth = derive_business_truth(business_config=_config(legal_profile=legal), assets=_assets())
    engine = AnthropicFrontendEngine(_Client(), storage=LocalStorageProvider(root_dir=tmp_path))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        engine.generate(
            business_config=_config(),  # deliberately different: the supplied truth must win
            creative_direction=_direction(),
            assets=[],
            platform_contract_version="1",
            business_id="b1",
            business_truth=truth,
        )
    assert truth.canonical_json() in captured["user"]
    assert "Nexo Reformas S.L." in captured["user"]


def test_generative_legal_pages_receive_authoritative_legal_data_and_escape_it():
    legal = LegalProfile(
        legal_name="Nexo <Reformas> {S.L.}",
        address=PostalAddress(street_address="Calle Mayor 1", locality="Valencia", country="ES"),
    )
    pages = build_legal_pages(derive_business_truth(business_config=_config(legal_profile=legal)))
    privacy = pages["src/pages/privacy.astro"]
    assert "Legal name: Nexo &lt;Reformas&gt; &#123;S.L.&#125;." in privacy  # escaped, never an Astro expression
    assert "Registered address: Calle Mayor 1, Valencia, ES." in privacy

    missing = build_legal_pages(derive_business_truth(business_config=_config()))["src/pages/privacy.astro"]
    assert "Legal name: not provided." in missing
    assert "Registered address: not provided." in missing
    assert "Contact for privacy questions: hola@nexo.example." in missing


def test_business_truth_is_a_frozen_value():
    truth = derive_business_truth(business_config=_config())
    assert isinstance(truth, BusinessTruth)
    with pytest.raises(Exception):  # noqa: B017 — any mutation error is acceptable
        truth.identity.name = "changed"  # type: ignore[misc]
