"""A complete, valid BusinessConfig for a Valencia home-renovation
business — mirrors packages/site-config's own exampleSiteConfig
(packages/site-config/src/example.ts): a fixture, documentation example,
and future AI-analyzer test case, built from the real schema rather than
hardcoded JSON elsewhere in the app. Loosely modeled on the real
apps/clients/reforma-casa-valencia client's service lineup, not copied
from it.
"""

from app.domain.business_config.automation import AutomationConfig, FollowUpConfig
from app.domain.business_config.brand import BrandColors, BrandConfig, BrandTypography
from app.domain.business_config.business_profile import (
    BusinessHoursRule,
    BusinessProfile,
    ContactInfo,
    Location,
    PostalAddress,
    ServiceOffering,
)
from app.domain.business_config.communication import CommunicationConfig, NotificationPreferences
from app.domain.business_config.config import BusinessConfig
from app.domain.business_config.integrations import IntegrationPreferences
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.business_config.website import SEOPreferences, WebsiteConfig
from app.domain.enums import BusinessVertical, IntegrationProvider, LeadSource, Weekday

EXAMPLE_REFORMA_VALENCIA_CONFIG = BusinessConfig(
    business_profile=BusinessProfile(
        name="Reforma Casa Valencia",
        slug="reforma-casa-valencia",
        industry=BusinessVertical.HOME_RENOVATION,
        description=(
            "Empresa de reformas integrales en Valencia, especializada en cocinas, "
            "banos y reformas completas de vivienda."
        ),
        location=Location(city="Valencia", region="Comunidad Valenciana", country="ES", postal_code="46001"),
        service_area=["Valencia", "Benimaclet", "Ruzafa", "Patraix", "Campanar", "Pla del Real", "Eixample"],
        services=[
            ServiceOffering(
                id="reforma-integral",
                name="Reforma integral",
                description="Reforma completa de vivienda, de principio a fin.",
                category="Reformas",
                featured=True,
            ),
            ServiceOffering(
                id="cocinas",
                name="Cocinas",
                description="Diseno y reforma de cocinas a medida.",
                category="Interiorismo",
            ),
            ServiceOffering(
                id="banos",
                name="Banos",
                description="Renovacion completa de cuartos de bano.",
                category="Interiorismo",
            ),
            ServiceOffering(
                id="electricidad-fontaneria",
                name="Electricidad y fontaneria",
                description="Instalaciones electricas y de fontaneria.",
                category="Instalaciones",
            ),
            ServiceOffering(
                id="pintura",
                name="Pintura",
                description="Pintura interior y exterior.",
                category="Acabados",
            ),
            ServiceOffering(
                id="diseno-planificacion",
                name="Diseno y planificacion",
                description="Diseno de espacios y planificacion de obra.",
                category="Diseno",
            ),
        ],
        target_customers=(
            "Propietarios de vivienda en Valencia que buscan una reforma integral o "
            "parcial con seguimiento profesional."
        ),
        contact=ContactInfo(
            email="info@reformacasavalencia.example",
            phone="+34 960 00 00 00",
            whatsapp="+34 600 00 00 00",
            website="https://reformacasavalencia.example",
            address=PostalAddress(
                street_address="Carrer de Colon 1",
                locality="Valencia",
                region="Comunidad Valenciana",
                postal_code="46004",
                country="ES",
            ),
        ),
        business_hours=[
            BusinessHoursRule(
                days=[Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY],
                opens="09:00",
                closes="18:00",
            ),
        ],
    ),
    brand=BrandConfig(
        tagline="Reformas con seguimiento profesional, de principio a fin.",
        colors=BrandColors(
            primary="#b45309", secondary="#0f766e", accent="#f59e0b", background="#ffffff", foreground="#111827"
        ),
        typography=BrandTypography(sans="Inter, system-ui, sans-serif", display="Fraunces, serif"),
        visual_style="warm, mediterranean, editorial",
    ),
    website=WebsiteConfig(
        enabled=True,
        seo=SEOPreferences(
            title="Reforma Casa Valencia | Reformas integrales en Valencia",
            description=(
                "Reformas integrales, cocinas y banos en Valencia con seguimiento profesional de principio a fin."
            ),
        ),
    ),
    lead_management=LeadManagementConfig(
        enabled=True,
        sources=[LeadSource.WEBSITE_FORM, LeadSource.PHONE, LeadSource.WHATSAPP],
        required_fields=["name", "phone", "service"],
        destination=IntegrationProvider.GOOGLE_SHEETS,
        acknowledgement=True,
        follow_up=True,
    ),
    communications=CommunicationConfig(
        email_enabled=True,
        phone_enabled=True,
        whatsapp_enabled=True,
        internal_notifications=NotificationPreferences(email=True, whatsapp=False, slack=False),
        customer_notifications=NotificationPreferences(email=True, whatsapp=True, slack=False),
    ),
    integrations=IntegrationPreferences(
        email=IntegrationProvider.GMAIL,
        spreadsheets=IntegrationProvider.GOOGLE_SHEETS,
    ),
    automation=AutomationConfig(
        lead_capture=True,
        lead_notifications=True,
        customer_acknowledgement=True,
        follow_up=FollowUpConfig(enabled=True, delay="2d", delay_hours=48),
    ),
)


# P2's second, deliberately contrasting golden fixture (P2.16/P2 Part H
# of the continuation prompt): a small, Instagram-led handmade-crochet
# business, used to prove the generative pipeline can produce a
# genuinely different experience from Reforma Valencia's — different
# navigation/storytelling/interaction, not just different colors.
#
# Deliberately narrower than EXAMPLE_REFORMA_VALENCIA_CONFIG above: no
# `contact`/`business_hours`/`address`/`brand` block is included, because
# no real Cositas y Puntos client data (a real logo, real product
# photos, a real contact channel) was ever made available in this
# session — see this task's final report for the exact reason. Every
# field below is either a structural default or one of the "known
# context" facts explicitly given as input to this session's real,
# already-generated Higgsfield exploration for this business (see
# tests/fixtures/cositas_creative_direction.json's own provenance notes)
# — never invented here. Do not add contact/address/hours/pricing to
# this fixture without a real source.
EXAMPLE_COSITAS_Y_PUNTOS_CONFIG = BusinessConfig(
    business_profile=BusinessProfile(
        name="Cositas y Puntos",
        slug="cositas-y-puntos",
        industry=BusinessVertical.OTHER,
        description=(
            "Artesana espanola independiente que crea amigurumi, crochet y piezas de punto "
            "hechas a mano. Vende a traves de Instagram y encargos personalizados; sin tienda "
            "fisica ni compra online."
        ),
        target_customers="Personas que buscan un regalo hecho a mano y personalizado.",
    ),
    lead_management=LeadManagementConfig(
        enabled=True,
        sources=[LeadSource.WHATSAPP, LeadSource.WEBSITE_FORM],
        required_fields=["name", "message"],
    ),
    automation=AutomationConfig(lead_capture=True),
)
