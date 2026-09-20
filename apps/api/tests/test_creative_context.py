"""CreativeContext (P2.4) — only verified, visually useful business knowledge
reaches an image model; operational and digital context never does. Pure
domain tests: no network, R2, Higgsfield or database."""

import json

from app.domain.business_config import BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.business_config.business_profile import ContactInfo, Location
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.creative_context import (
    ExcludedReason,
    build_creative_context,
)
from app.domain.enums import BusinessVertical

DESCRIPTION = (
    "Pequeña marca artesanal. Actualmente no dispone de página web; su principal presencia online es Instagram. "
    "El objetivo es una presencia digital en formato catálogo + contacto (sin ecommerce, carrito ni pago online)."
)


def _context(
    *services: str,
    industry: BusinessVertical = BusinessVertical.OTHER,
    description: str | None = DESCRIPTION,
    **profile_fields,
):
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=industry,
            description=description,
            services=[
                ServiceOffering(id=f"svc-{i}", name=name, description="Descripcion.")
                for i, name in enumerate(services, start=1)
            ],
            **profile_fields,
        )
    )
    return build_creative_context(build_creative_brief(business_config=config))


def _excluded(context, field: str) -> list:
    return [item for item in context.excluded if item.field == field]


def test_free_text_description_and_target_customers_are_never_forwarded():
    context = _context("Llaveros de lana", target_customers="Visitantes que llegan desde Instagram y redes sociales.")

    dumped = context.model_dump_json().lower()

    assert "instagram" not in dumped and "página web" not in dumped and "ecommerce" not in dumped
    for field in ("description", "target_customers"):
        [item] = _excluded(context, field)
        assert item.reason is ExcludedReason.FREE_TEXT_NOT_FORWARDED


def test_operational_and_digital_services_are_excluded_by_a_conservative_label_filter():
    context = _context(
        "Diseño web",
        "SEO y posicionamiento",
        "Gestión de Instagram",
        "Tienda online",
        "Marketing digital",
        "Llaveros de lana",
    )

    assert context.subject_categories == ["Llaveros de lana"]
    [item] = _excluded(context, "services")
    assert item.reason is ExcludedReason.OPERATIONAL_OR_DIGITAL_TERM and item.count == 5


def test_contact_details_urls_and_social_handles_in_a_label_are_excluded():
    context = _context(
        "Escríbenos a hola@cositas.es",
        "Llama al +34 600 123 456",
        "Visita www.cositas.es",
        "Sígueme en @cositas_y_puntos",
        "Cestas personalizadas",
    )

    assert context.subject_categories == ["Cestas personalizadas"]
    [item] = _excluded(context, "services")
    assert item.reason is ExcludedReason.CONTACT_OR_HANDLE_PATTERN and item.count == 4


def test_contact_information_never_appears_anywhere_in_the_context():
    context = _context(
        "Llaveros de lana",
        contact=ContactInfo(email="hola@cositas.es", phone="+34600123456", website="https://cositas.es"),
    )

    dumped = context.model_dump_json().lower()

    assert "hola@" not in dumped and "+34" not in dumped and "cositas.es" not in dumped


def test_technical_and_deployment_terms_are_excluded():
    context = _context("Hosting y dominio", "Integración con CRM", "Software a medida", "Tartas de pañales")
    assert context.subject_categories == ["Tartas de pañales"]


def test_verified_useful_visual_facts_survive():
    context = _context("Amigurumis artesanales hechos a mano", "Llaveros de lana", "Tartas de pañales")

    assert context.subject_categories == [
        "Amigurumis artesanales hechos a mano",
        "Llaveros de lana",
        "Tartas de pañales",
    ]
    assert "services" in context.included_fields
    assert "subject_categories" not in context.unknown


def test_a_visually_meaningful_industry_is_kept_but_a_business_model_label_is_not():
    restaurant = _context(industry=BusinessVertical.RESTAURANT)
    ecommerce = _context(industry=BusinessVertical.ECOMMERCE)

    assert restaurant.business_category == "restaurant" and "industry" in restaurant.included_fields
    assert ecommerce.business_category is None
    assert "business_category" in ecommerce.unknown
    [item] = _excluded(ecommerce, "industry")
    assert item.reason is ExcludedReason.NOT_A_VISUAL_SUBJECT


def test_missing_product_facts_stay_unknown_and_are_never_invented():
    context = _context(description=None)

    assert context.subject_categories == []
    assert "subject_categories" in context.unknown
    assert "services" not in context.included_fields


def test_missing_venue_facts_do_not_become_premises_and_a_known_location_is_not_used():
    without = _context(description=None)
    with_location = _context("Llaveros de lana", location=Location(city="Valencia", country="ES"))

    for context in (without, with_location):
        dumped = context.model_dump_json().lower()
        assert "valencia" not in dumped and "workshop" not in dumped and "taller" not in dumped
    [item] = _excluded(with_location, "location")
    assert item.reason is ExcludedReason.NOT_USED_FOR_IMAGERY


def test_the_business_name_is_never_a_subject_and_is_recorded_as_excluded():
    context = _context("Llaveros de Cositas y Puntos", "Llaveros de lana")

    assert context.subject_categories == ["Llaveros de lana"]
    assert _excluded(context, "business_name")[0].reason is ExcludedReason.BUSINESS_NAME_NOT_FOR_IMAGES
    assert "cositas" not in context.model_dump_json().lower().replace("business_name_is_rendered", "")


def test_only_short_labels_can_be_subjects():
    long_label = "Servicio completo de creación de piezas de punto y crochet totalmente a medida para cada cliente"

    context = _context(long_label, "Llaveros de lana")

    assert context.subject_categories == ["Llaveros de lana"]
    assert _excluded(context, "services")[0].reason is ExcludedReason.NOT_A_SHORT_LABEL


def test_subjects_are_capped_and_deduplicated():
    context = _context("A uno", "A dos", "A tres", "A cuatro", "A cinco", "a uno")

    assert context.subject_categories == ["A uno", "A dos", "A tres", "A cuatro"]
    assert _excluded(context, "services")[0].reason is ExcludedReason.OVER_LIMIT


def test_operational_website_configuration_is_always_recorded_as_excluded():
    context = _context("Llaveros de lana")
    assert _excluded(context, "website_configuration")[0].reason is ExcludedReason.OPERATIONAL_CONFIGURATION


def test_the_context_is_deterministic_and_stores_reason_codes_never_excluded_text():
    first, second = _context("Diseño web", "Llaveros de lana"), _context("Diseño web", "Llaveros de lana")

    assert first == second
    serialized = json.dumps([item.model_dump(mode="json") for item in first.excluded])
    assert "Diseño" not in serialized and "Instagram" not in serialized
