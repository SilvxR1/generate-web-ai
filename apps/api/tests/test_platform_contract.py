"""validate_platform_contract (app.qa.platform_contract) — P2.7/P2.8
machine-verifiable contract tests: dead CTAs, disconnected lead forms,
missing legal/consent/analytics/SEO, WhatsApp-when-configured. Engine-
agnostic: every test builds a plain `dict[str, bytes]` files map, the
same shape either engine's build produces."""

import json

import pytest

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.business_config.whatsapp import WhatsAppConfig
from app.domain.enums import BusinessVertical, PlatformContractSeverity
from app.publishing.public_origin import public_origin_problem
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
        # A8.3.4-P0: a compliant build renders where its lead form and
        # analytics beacon actually submit to.
        b'<script type="application/json" id="lead-submission-config">'
        b'{"businessId":"biz-1","apiBaseUrl":"https://api.example.com"}</script>'
        b'<script>var apiBaseUrl = "https://api.example.com";</script>'
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
    files = {"index.html": b"<html><body><form data-gwa-lead-form></form></body></html>", **_LEGAL_PAGES}
    result = validate_platform_contract(files, business_config=config)

    assert "disconnected_lead_form" in {f.rule for f in result.blocking_violations}


def test_lead_form_wired_via_platform_sdk_passes():
    config = _config(automation=AutomationConfig(lead_capture=True))
    files = {
        "index.html": b"<html><body><form data-gwa-lead-form></form></body></html>",
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


# --- A8.3.4-P0: the lead form / analytics must have a real endpoint ----------


def _index_with_runtime(api_base_url: str | None, *, business_id: str = "biz-1", form: bool = True) -> bytes:
    config = json.dumps({"businessId": business_id, "apiBaseUrl": api_base_url})
    return (
        "<html><head><title>Reforma Valencia</title>"
        '<meta name="description" content="Reformas integrales en Valencia">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
        + ("<form data-gwa-lead-form>...</form>" if form else "")
        + f'<script type="application/json" id="lead-submission-config">{config}</script>'
        + f'<script>var apiBaseUrl = "{api_base_url or ""}";</script>'
        + "</body></html>"
    ).encode()


def _files(index: bytes, *, analytics: bool = True) -> dict[str, bytes]:
    script = b"window.gwaConsent={}; function submit(){ submitLead(); }"
    if analytics:
        script += b" window.gwaAnalytics={};"
    return {"index.html": index, "assets/main.js": script, **_LEGAL_PAGES}


def _rules(result, severity=None):
    return [f.rule for f in result.findings if severity is None or f.severity is severity]


def test_A_lead_capture_expected_with_no_api_origin_is_blocking():
    result = validate_platform_contract(_files(_index_with_runtime("")), business_config=_config())

    assert "lead_endpoint_unconfigured" in _rules(result, PlatformContractSeverity.BLOCKING)
    assert result.passed is False


def test_B_lead_capture_expected_with_a_valid_api_origin_passes():
    result = validate_platform_contract(
        _files(_index_with_runtime("https://generate-web-ai-repo-production.up.railway.app")), business_config=_config()
    )

    assert "lead_endpoint_unconfigured" not in _rules(result)
    assert "analytics_endpoint_unconfigured" not in _rules(result)
    assert result.passed is True


def test_C_no_lead_capture_expected_is_not_blocked_by_a_missing_origin():
    no_leads = _config(lead_management=LeadManagementConfig(enabled=False, sources=[]))
    result = validate_platform_contract(_files(_index_with_runtime("", form=False)), business_config=no_leads)

    assert "lead_endpoint_unconfigured" not in _rules(result)
    assert _rules(result, PlatformContractSeverity.BLOCKING) == []


def test_D_analytics_beacon_with_no_origin_is_an_advisory_finding():
    no_leads = _config(lead_management=LeadManagementConfig(enabled=False, sources=[]))
    result = validate_platform_contract(_files(_index_with_runtime("", form=False)), business_config=no_leads)

    assert "analytics_endpoint_unconfigured" in _rules(result, PlatformContractSeverity.ADVISORY)
    assert result.passed is True


def test_E_no_analytics_beacon_means_no_analytics_endpoint_requirement():
    no_leads = _config(lead_management=LeadManagementConfig(enabled=False, sources=[]))
    result = validate_platform_contract(
        _files(_index_with_runtime("", form=False), analytics=False), business_config=no_leads
    )

    assert "analytics_endpoint_unconfigured" not in _rules(result)


@pytest.mark.parametrize(
    "origin",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "https://user:pw@api.example.com",
        "https://api.example.com/public",
        "https://api.example.com?x=1",
        "http://api.example.com",
        "not a url",
    ],
)
def test_F_a_malformed_or_unsafe_origin_is_blocking(origin):
    result = validate_platform_contract(_files(_index_with_runtime(origin)), business_config=_config())

    assert "lead_endpoint_unconfigured" in _rules(result, PlatformContractSeverity.BLOCKING)


def test_a_missing_business_id_is_blocking_even_with_a_valid_origin():
    result = validate_platform_contract(
        _files(_index_with_runtime("https://api.example.com", business_id="")), business_config=_config()
    )

    assert "lead_endpoint_unconfigured" in _rules(result, PlatformContractSeverity.BLOCKING)


def test_a_form_wired_directly_to_an_n8n_webhook_needs_no_api_origin():
    index = _index_with_runtime("").replace(
        b"<form data-gwa-lead-form>", b'<form data-gwa-lead-form action="https://n8n.example.com/webhook/x">'
    )
    result = validate_platform_contract(_files(index), business_config=_config())

    assert "lead_endpoint_unconfigured" not in _rules(result)


def test_the_generative_platform_config_counts_as_a_runtime_config():
    index = _index_with_runtime("").replace(b'id="lead-submission-config"', b'id="platform-config"')
    index = index.replace(b'"apiBaseUrl": ""', b'"apiBaseUrl": "https://api.example.com"')
    result = validate_platform_contract(_files(index), business_config=_config())

    assert "lead_endpoint_unconfigured" not in _rules(result)


@pytest.mark.parametrize(
    ("origin", "ok"),
    [
        ("https://generate-web-ai-repo-production.up.railway.app", True),
        ("https://api.example.com/", True),
        ("https://api.example.com:8443", True),
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://host.docker.internal:8000", True),
        ("", False),
        (None, False),
        ("http://api.example.com", False),
        ("ftp://api.example.com", False),
        ("https://", False),
        ("https://a@b.example.com", False),
        ("https://api.example.com:notaport", False),
        ("https://api.example.com#frag", False),
    ],
)
def test_public_origin_validation(origin, ok):
    assert (public_origin_problem(origin) is None) is ok


# --- A8.3.4-P0.2: the effective CSP must let the scripts reach the API ------

_API = "https://api.example.com"


def _files_with_csp(api_base_url: str | None, csp: str | None, *, meta_csp: str | None = None) -> dict[str, bytes]:
    index = _index_with_runtime(api_base_url)
    if meta_csp is not None:
        index = index.replace(
            b"</head>", f'<meta http-equiv="Content-Security-Policy" content="{meta_csp}"></head>'.encode()
        )
    files = _files(index)
    if csp is not None:
        files["_headers"] = f"/*\n  Content-Security-Policy: {csp}\n  X-Frame-Options: DENY\n".encode()
    return files


def _csp_blocked(files) -> bool:
    return "public_api_csp_disconnected" in _rules(
        validate_platform_contract(files, business_config=_config()), PlatformContractSeverity.BLOCKING
    )


def test_csp_A_runtime_origin_with_connect_src_self_only_is_blocking():
    assert _csp_blocked(_files_with_csp(_API, "default-src 'self'; connect-src 'self'"))


def test_csp_B_runtime_origin_allowed_by_connect_src_passes():
    result = validate_platform_contract(
        _files_with_csp(_API, f"default-src 'self'; connect-src 'self' {_API}"), business_config=_config()
    )

    assert result.passed, [f.message for f in result.blocking_violations]
    assert "public_api_csp_disconnected" not in _rules(result)


def test_csp_the_real_generator_output_passes():
    from app.publishing.security_headers import generate_headers_file

    files = _files(_index_with_runtime(_API))
    files["_headers"] = generate_headers_file(public_api_origin=_API)
    assert not _csp_blocked(files)
    files["_headers"] = generate_headers_file()  # the pre-P0.2 output
    assert _csp_blocked(files)


@pytest.mark.parametrize(
    "allowed",
    [
        "https://other.example.com",
        "https://api.example.com.evil.test",
        "https://evil-api.example.com",
        "http://api.example.com:8080",
        "https://api.example.com:8443",
        "wss://api.example.com",
        "https://api.example.com/public/",
        "'self'",
    ],
)
def test_csp_D_a_different_or_lookalike_origin_is_blocking(allowed):
    assert _csp_blocked(_files_with_csp(_API, f"connect-src 'self' {allowed}"))


def test_csp_E_a_malformed_origin_is_blocked_by_the_origin_rules_not_invented_here():
    result = validate_platform_contract(
        _files_with_csp("http://api.example.com", "connect-src 'self'"), business_config=_config()
    )

    assert "lead_endpoint_unconfigured" in _rules(result, PlatformContractSeverity.BLOCKING)
    assert "public_api_csp_disconnected" not in _rules(result)


@pytest.mark.parametrize("origin", ["", None])
def test_csp_F_no_external_api_requirement_is_not_a_csp_finding(origin):
    result = validate_platform_contract(_files_with_csp(origin, "connect-src 'self'"), business_config=_config())

    assert "public_api_csp_disconnected" not in _rules(result)


def test_csp_F_no_csp_at_all_restricts_nothing():
    assert not _csp_blocked(_files_with_csp(_API, None))


@pytest.mark.parametrize(
    "csp",
    [
        f"CONNECT-SRC   'self'\t{_API.upper()} ;default-src 'none'",  # case, whitespace, ordering
        f"default-src 'self' {_API}",  # connect-src falls back to default-src
        f"connect-src {_API}:443",  # explicit default port
        "connect-src https://*.example.com",  # subdomain wildcard
        f"connect-src {_API}/",  # whole-origin path
    ],
)
def test_csp_parsing_accepts_every_equivalent_allowing_form(csp):
    assert not _csp_blocked(_files_with_csp(_API, csp))


def test_csp_only_the_first_connect_src_directive_counts():
    assert _csp_blocked(_files_with_csp(_API, f"connect-src 'self'; connect-src {_API}"))


def test_csp_every_enforced_policy_must_allow_the_origin():
    allowing = f"connect-src 'self' {_API}"
    assert _csp_blocked(_files_with_csp(_API, allowing, meta_csp="connect-src 'self'"))
    assert not _csp_blocked(_files_with_csp(_API, allowing, meta_csp=allowing))


def test_csp_analytics_only_origin_is_also_covered():
    """The analytics beacon's literal counts even without a lead form."""
    index = _index_with_runtime(_API, form=False)
    files = _files(index)
    files["_headers"] = b"/*\n  Content-Security-Policy: connect-src 'self'\n"

    assert _csp_blocked(files)
