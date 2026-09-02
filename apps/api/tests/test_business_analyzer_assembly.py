"""app.analysis.assembly: BusinessAnalysisOutput -> BusinessAnalysisResult.
Pure, provider-agnostic mapping tests — no LLM, no HTTP. Covers a
complete briefing, an incomplete one, ambiguous/invalid sub-fields, and
that the result is always a real, schema-validated BusinessConfig (or
none at all) — never a guess."""

from app.analysis.assembly import assemble_result, slugify
from app.analysis.schema import (
    BusinessAnalysisOutput,
    RawContactInfo,
    RawLocation,
    RawServiceOffering,
)
from app.domain.enums import BusinessVertical, LeadSource

# --- slugify --------------------------------------------------------------


def test_slugify_strips_accents_and_punctuation():
    assert slugify("Peluquería Núñez & Hijos!") == "peluqueria-nunez-hijos"


def test_slugify_of_non_latin_text_is_empty_not_a_guess():
    assert slugify("北京烤鸭店") == ""


# --- complete briefing ------------------------------------------------------


def test_complete_briefing_produces_a_valid_business_config():
    raw = BusinessAnalysisOutput(
        business_name="Sacri Barber",
        industry=BusinessVertical.OTHER,
        description="Barberia clasica en el centro de la ciudad.",
        location=RawLocation(city="Valencia", country="es", postal_code="46001"),
        services=[RawServiceOffering(name="Corte clasico", description="Corte de pelo tradicional a tijera.")],
        target_customers="Hombres de todas las edades que buscan un servicio clasico.",
        contact=RawContactInfo(email="hola@sacribarber.example", phone="+34 960 00 00 00"),
        lead_sources=[LeadSource.WHATSAPP],
    )

    result = assemble_result(raw)

    assert result.proposed_config is not None
    profile = result.proposed_config.business_profile
    assert profile.name == "Sacri Barber"
    assert profile.slug == "sacri-barber"
    assert profile.industry is BusinessVertical.OTHER
    assert profile.location is not None and profile.location.country == "ES"
    assert profile.contact is not None and profile.contact.email == "hola@sacribarber.example"
    assert [s.name for s in profile.services] == ["Corte clasico"]
    assert result.proposed_config.lead_management.enabled is True
    assert result.proposed_config.lead_management.sources == [LeadSource.WHATSAPP]
    assert result.missing_information == []
    assert result.questions == []


# --- incomplete briefing -----------------------------------------------------


def test_missing_business_name_yields_no_proposal_and_a_question():
    result = assemble_result(BusinessAnalysisOutput())

    assert result.proposed_config is None
    assert any("name" in item for item in result.missing_information)
    assert result.questions


def test_missing_industry_defaults_to_other_and_is_flagged():
    result = assemble_result(BusinessAnalysisOutput(business_name="Cafe del Mar"))

    assert result.proposed_config is not None
    assert result.proposed_config.business_profile.industry is BusinessVertical.OTHER
    assert any("industry" in item for item in result.missing_information)


# --- ambiguous / invalid sub-fields — never invented, never crash ----------


def test_location_missing_country_is_left_unset_and_flagged():
    raw = BusinessAnalysisOutput(business_name="Cafe del Mar", location=RawLocation(city="Alicante"))

    result = assemble_result(raw)

    assert result.proposed_config is not None
    assert result.proposed_config.business_profile.location is None
    assert any("location" in item for item in result.missing_information)


def test_location_with_bad_country_code_is_dropped_not_guessed():
    raw = BusinessAnalysisOutput(
        business_name="Cafe del Mar", location=RawLocation(city="Alicante", country="Espana")
    )

    result = assemble_result(raw)

    assert result.proposed_config is not None
    assert result.proposed_config.business_profile.location is None
    assert any("country" in item for item in result.missing_information)


def test_invalid_contact_field_is_dropped_while_valid_ones_survive():
    raw = BusinessAnalysisOutput(
        business_name="Cafe del Mar",
        contact=RawContactInfo(email="hola@cafedelmar.example", phone="not-a-phone-number"),
    )

    result = assemble_result(raw)

    assert result.proposed_config is not None
    contact = result.proposed_config.business_profile.contact
    assert contact is not None
    assert contact.email == "hola@cafedelmar.example"
    assert contact.phone is None
    assert any("contact.phone" in item for item in result.missing_information)


def test_duplicate_service_names_get_disambiguated_ids():
    raw = BusinessAnalysisOutput(
        business_name="Cafe del Mar",
        services=[
            RawServiceOffering(name="Cafe", description="Cafe de especialidad."),
            RawServiceOffering(name="Cafe", description="Cafe para llevar."),
        ],
    )

    result = assemble_result(raw)

    assert result.proposed_config is not None
    ids = [s.id for s in result.proposed_config.business_profile.services]
    assert len(ids) == len(set(ids))


def test_automation_flags_are_applied_only_when_stated():
    raw = BusinessAnalysisOutput(
        business_name="Cafe del Mar",
        automation_lead_capture=True,
    )

    result = assemble_result(raw)

    assert result.proposed_config is not None
    automation = result.proposed_config.automation
    assert automation.lead_capture is True
    # Untouched field keeps AutomationConfig's own default — never
    # invented from silence.
    assert automation.lead_notifications is False


def test_communications_keep_business_config_defaults():
    """communication-channel preferences are no longer part of what the
    analyzer extracts (see BusinessAnalysisOutput's docstring) — the
    proposed BusinessConfig must still validate with CommunicationConfig's
    own defaults, never a crash or a guessed value."""
    result = assemble_result(BusinessAnalysisOutput(business_name="Cafe del Mar"))

    assert result.proposed_config is not None
    communications = result.proposed_config.communications
    assert communications.email_enabled is True
    assert communications.phone_enabled is True
    assert communications.whatsapp_enabled is False
