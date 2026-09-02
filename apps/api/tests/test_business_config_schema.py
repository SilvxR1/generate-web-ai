"""BusinessConfig (app.domain.business_config): minimal/complete valid
configs, invalid input, unknown values, and JSON round-tripping — the
"Schema" bullet of the business-configuration-system phase."""

import pytest
from pydantic import ValidationError

from app.domain.business_config import (
    EXAMPLE_REFORMA_VALENCIA_CONFIG,
    BrandColors,
    BrandConfig,
    BrandTypography,
    BusinessConfig,
    BusinessHoursRule,
    BusinessProfile,
    ContactInfo,
    Location,
    ServiceOffering,
)
from app.domain.enums import BusinessVertical, IntegrationProvider, LeadSource, Weekday


def _minimal_profile(**overrides: object) -> BusinessProfile:
    data = {"name": "Sacri Barber", "slug": "sacri-barber", "industry": BusinessVertical.OTHER}
    data.update(overrides)
    return BusinessProfile(**data)


def test_minimum_valid_business_config():
    config = BusinessConfig(business_profile=_minimal_profile())

    assert config.schema_version == 1
    assert config.brand is None
    assert config.website.enabled is True
    assert config.lead_management.sources == [LeadSource.WEBSITE_FORM]
    assert config.automation.follow_up.enabled is False


def test_complete_business_config_matches_the_example_fixture():
    config = EXAMPLE_REFORMA_VALENCIA_CONFIG

    assert config.business_profile.slug == "reforma-casa-valencia"
    assert config.business_profile.industry is BusinessVertical.HOME_RENOVATION
    assert len(config.business_profile.services) == 6
    assert config.brand is not None and config.brand.colors.primary == "#b45309"
    assert config.integrations.spreadsheets is IntegrationProvider.GOOGLE_SHEETS
    assert config.automation.follow_up.delay == "2d"


def test_business_config_requires_business_profile():
    with pytest.raises(ValidationError):
        BusinessConfig()


def test_business_config_rejects_unknown_schema_version():
    with pytest.raises(ValidationError, match="Unsupported schema_version"):
        BusinessConfig(schema_version=2, business_profile=_minimal_profile())


def test_business_config_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        BusinessConfig(business_profile=_minimal_profile(), not_a_real_field=True)


def test_business_profile_rejects_unknown_industry():
    with pytest.raises(ValidationError):
        _minimal_profile(industry="not_a_real_industry")


def test_business_profile_rejects_bad_slug():
    with pytest.raises(ValidationError):
        _minimal_profile(slug="Not A Valid Slug!")


def test_contact_info_rejects_invalid_email():
    with pytest.raises(ValidationError):
        ContactInfo(email="not-an-email")


def test_contact_info_rejects_unrecognizable_phone():
    with pytest.raises(ValidationError):
        ContactInfo(phone="call me maybe")


def test_contact_info_allows_all_fields_optional():
    contact = ContactInfo()
    assert contact.email is None
    assert contact.address is None


def test_location_requires_two_letter_country_code():
    with pytest.raises(ValidationError):
        Location(city="Valencia", country="Spain")


def test_business_hours_rule_rejects_bad_time_format():
    with pytest.raises(ValidationError):
        BusinessHoursRule(days=[Weekday.MONDAY], opens="9am", closes="18:00")


def test_business_hours_rule_requires_at_least_one_day():
    with pytest.raises(ValidationError):
        BusinessHoursRule(days=[], opens="09:00", closes="18:00")


def test_service_offering_requires_slug_like_id():
    with pytest.raises(ValidationError):
        ServiceOffering(id="Not A Slug", name="Cocinas", description="Reforma de cocinas.")


def test_service_offering_rejects_negative_price():
    with pytest.raises(ValidationError):
        ServiceOffering(id="cocinas", name="Cocinas", description="Reforma de cocinas.", price_from=-10)


def test_brand_config_requires_colors_and_typography():
    with pytest.raises(ValidationError):
        BrandConfig(tagline="Only a tagline")


def test_brand_config_valid_minimum():
    brand = BrandConfig(
        colors=BrandColors(primary="#000", secondary="#111", accent="#222", background="#fff", foreground="#000"),
        typography=BrandTypography(sans="Inter"),
    )
    assert brand.typography.display is None


def test_business_config_json_round_trip():
    original = EXAMPLE_REFORMA_VALENCIA_CONFIG

    as_json = original.model_dump_json()
    restored = BusinessConfig.model_validate_json(as_json)

    assert restored == original
    assert restored.model_dump(mode="json") == original.model_dump(mode="json")
