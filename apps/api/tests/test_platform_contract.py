"""validate_platform_contract (app.qa.platform_contract) — P2.7/P2.8
machine-verifiable contract tests: dead CTAs, disconnected lead forms,
missing legal/consent/analytics/SEO, WhatsApp-when-configured. Engine-
agnostic: every test builds a plain `dict[str, bytes]` files map, the
same shape either engine's build produces."""

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.whatsapp import WhatsAppConfig
from app.domain.enums import BusinessVertical
from app.qa.platform_contract import validate_platform_contract


def _legal_page(title: str) -> bytes:
    return (
        f'<html><head><title>{title}</title><meta name="description" content="{title} policy">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>p</body></html>'
    ).encode()


_LEGAL_PAGES = {
    "privacy/index.html": _legal_page("Privacy"),
    "terms/index.html": _legal_page("Terms"),
    "cookies/index.html": _legal_page("Cookies"),
}


def _config(**overrides) -> BusinessConfig:
    profile = BusinessProfile(
        name="Reforma Valencia", slug="reforma-valencia", industry=BusinessVertical.HOME_RENOVATION
    )
    fields = {"business_profile": profile}
    fields.update(overrides)
    return BusinessConfig(**fields)


def _compliant_index_html() -> bytes:
    return (
        b"<html><head><title>Reforma Valencia</title>"
        b'<meta name="description" content="Reformas integrales en Valencia">'
        b'<meta name="viewport" content="width=device-width, initial-scale=1">'
        b"</head><body>"
        b'<a href="#servicios">Servicios</a>'
        b'<section id="servicios">...</section>'
        b"<form data-gwa-lead-form>...</form>"
        b"</body></html>"
    )


def _compliant_script() -> bytes:
    return b"window.gwaConsent={}; window.gwaAnalytics={}; function submit(){ submitLead(); }"


def test_fully_compliant_build_passes_with_no_blocking_violations():
    files = {"index.html": _compliant_index_html(), "assets/main.js": _compliant_script(), **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=_config())

    assert result.passed is True
    assert result.blocking_violations == []


def test_dead_cta_href_hash_is_blocking():
    files = {"index.html": b'<html><body><a href="#">Click</a></body></html>'}
    result = validate_platform_contract(files, business_config=_config())

    rules = {f.rule for f in result.blocking_violations}
    assert "dead_cta_href_hash" in rules
    assert result.passed is False


def test_anchor_targeting_nonexistent_section_is_blocking():
    files = {"index.html": b'<html><body><a href="#pricing">Pricing</a></body></html>'}
    result = validate_platform_contract(files, business_config=_config())

    assert "broken_anchor_target" in {f.rule for f in result.blocking_violations}


def test_anchor_targeting_real_section_is_not_flagged():
    files = {"index.html": b'<html><body><a href="#pricing">Pricing</a><div id="pricing"></div></body></html>'}
    result = validate_platform_contract(files, business_config=_config())

    assert "broken_anchor_target" not in {f.rule for f in result.findings}


def test_missing_lead_form_is_blocking_when_lead_capture_enabled():
    config = _config(automation=AutomationConfig(lead_capture=True))
    files = {"index.html": b"<html><body>no form here</body></html>", **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=config)

    assert "missing_lead_form" in {f.rule for f in result.blocking_violations}


def test_lead_form_present_but_not_wired_is_blocking():
    config = _config(automation=AutomationConfig(lead_capture=True))
    files = {"index.html": b'<html><body><form data-gwa-lead-form></form></body></html>', **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=config)

    assert "disconnected_lead_form" in {f.rule for f in result.blocking_violations}


def test_lead_form_wired_via_platform_sdk_passes():
    config = _config(automation=AutomationConfig(lead_capture=True))
    files = {
        "index.html": b'<html><body><form data-gwa-lead-form></form></body></html>',
        "assets/main.js": b"submitLead();",
        **_LEGAL_PAGES,
    }
    result = validate_platform_contract(files, business_config=config)

    assert "disconnected_lead_form" not in {f.rule for f in result.findings}
    assert "missing_lead_form" not in {f.rule for f in result.findings}


def test_missing_legal_pages_are_blocking():
    files = {"index.html": _compliant_index_html(), "assets/main.js": _compliant_script()}
    result = validate_platform_contract(files, business_config=_config())

    rules = {f.rule for f in result.blocking_violations}
    assert "missing_legal_page" in rules
    assert sum(1 for f in result.blocking_violations if f.rule == "missing_legal_page") == 3


def test_missing_consent_mechanism_is_blocking():
    files = {"index.html": _compliant_index_html(), "assets/main.js": b"", **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=_config())

    assert "missing_consent_mechanism" in {f.rule for f in result.blocking_violations}


def test_missing_analytics_beacon_is_advisory_not_blocking():
    files = {"index.html": _compliant_index_html(), "assets/main.js": b"window.gwaConsent={};", **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=_config())

    assert "missing_analytics_beacon" in {f.rule for f in result.advisory_findings}
    assert "missing_analytics_beacon" not in {f.rule for f in result.blocking_violations}


def test_whatsapp_required_only_when_configured_enabled():
    files = {"index.html": _compliant_index_html(), "assets/main.js": _compliant_script(), **_LEGAL_PAGES}

    without_whatsapp = validate_platform_contract(files, business_config=_config())
    assert "missing_whatsapp_link" not in {f.rule for f in without_whatsapp.findings}

    with_whatsapp = _config(whatsapp=WhatsAppConfig(enabled=True, phone_number="+34600000000"))
    result = validate_platform_contract(files, business_config=with_whatsapp)
    assert "missing_whatsapp_link" in {f.rule for f in result.blocking_violations}

    files_with_link = {**files, "index.html": files["index.html"] + b'<a href="https://wa.me/34600000000">WA</a>'}
    result_ok = validate_platform_contract(files_with_link, business_config=with_whatsapp)
    assert "missing_whatsapp_link" not in {f.rule for f in result_ok.findings}


def test_missing_seo_title_and_description_are_blocking():
    files = {"index.html": b"<html><head></head><body>no title, no description</body></html>", **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=_config())

    rules = {f.rule for f in result.blocking_violations}
    assert "missing_seo_title" in rules
    assert "missing_seo_description" in rules


def test_animation_without_reduced_motion_guard_is_advisory():
    files = {
        "index.html": _compliant_index_html(),
        "assets/main.css": b"@keyframes spin { from { transform: rotate(0); } }",
        **_LEGAL_PAGES,
    }
    result = validate_platform_contract(files, business_config=_config())

    assert "animation_without_reduced_motion_guard" in {f.rule for f in result.advisory_findings}


def test_platform_contract_never_flags_color_or_font_choices():
    """P2.7: PlatformContract must never dictate visual styling — two
    wildly different color/font choices, both otherwise compliant, must
    both pass identically."""
    base_html = _compliant_index_html()
    warm_css = b"body { color: #b35c2e; font-family: 'Comic Sans MS'; }"
    cold_css = b"body { color: #000000; font-family: Helvetica; }"

    warm = validate_platform_contract(
        {
            "index.html": base_html,
            "assets/warm.css": warm_css,
            "assets/main.js": _compliant_script(),
            **_LEGAL_PAGES,
        },
        business_config=_config(),
    )
    cold = validate_platform_contract(
        {
            "index.html": base_html,
            "assets/cold.css": cold_css,
            "assets/main.js": _compliant_script(),
            **_LEGAL_PAGES,
        },
        business_config=_config(),
    )

    assert warm.passed is True
    assert cold.passed is True
