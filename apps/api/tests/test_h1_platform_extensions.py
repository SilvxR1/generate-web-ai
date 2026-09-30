"""H1 — the narrow shared-code changes the Higgsfield source adapter
needed, each proven not to relax anything for existing sites:

- TruthContract: an email that appears in shipped JS ONLY as a form
  `placeholder` is example input text, not a published contact; a real
  unauthorized email is still BLOCKING.
- security_headers.CspExtensions: opt-in, trusted per-source-family CSP
  additions; the default `_headers` output is byte-identical.
- legal_pages.legal_page_content: the Astro legal pages are rendered from
  it unchanged.
- inline_script_hashes: hashes what the browser hashes (U+0000 -> U+FFFD,
  CRLF -> LF), so a real CSP no longer blocks such scripts; unchanged for
  every ordinary script.
"""

import base64
import hashlib

import pytest

from app.creative.frontend_engine.build import inline_script_hashes
from app.creative.frontend_engine.legal_pages import build_legal_pages, legal_page_content
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_truth import derive_business_truth
from app.domain.enums import BusinessVertical
from app.publishing.security_headers import CspExtensions, generate_headers_file
from app.qa.truth_contract import validate_truth_contract

_PAGE = (
    b"<html><head><title>Nexo Reformas</title></head><body><h1>Reformas</h1>"
    b'<form><input type="email" placeholder="nombre@correo.com"></form></body></html>'
)


def _truth():
    profile = BusinessProfile(name="Nexo Reformas", slug="nexo-reformas", industry=BusinessVertical.HOME_RENOVATION)
    return derive_business_truth(business_config=BusinessConfig(business_profile=profile))


def _email_rules(js: str) -> set[str]:
    result = validate_truth_contract({"index.html": _PAGE, "assets/app.js": js.encode()}, business_truth=_truth())
    return {f.rule for f in result.violations if f.rule == "truth.contact.email_unauthorized"}


# --- TruthContract: placeholder emails ---------------------------------------


def test_a_form_placeholder_email_in_js_is_not_a_published_business_email():
    js = 'jsx("input",{autoComplete:"email",id:"email",name:"email",placeholder:"nombre@correo.com",type:"email"})'
    assert _email_rules(js) == set()


def test_an_unauthorized_email_rendered_by_js_is_still_blocked():
    assert _email_rules('jsx("a",{href:"mailto:ventas@nexo.example",children:"Escríbenos"})') == {
        "truth.contact.email_unauthorized"
    }


def test_a_placeholder_email_that_is_also_published_elsewhere_is_still_blocked():
    js = 'jsx("input",{placeholder:"info@nexo.example"});jsx("a",{href:"mailto:info@nexo.example"})'
    assert _email_rules(js) == {"truth.contact.email_unauthorized"}


def test_placeholder_like_text_that_is_not_a_placeholder_prop_is_still_blocked():
    assert _email_rules('const note = "placeholder text: info@nexo.example";') == {"truth.contact.email_unauthorized"}


# --- security_headers.CspExtensions ------------------------------------------


def test_default_headers_are_unchanged_by_the_extension_point():
    csp = generate_headers_file(script_hashes=frozenset({"abc=="}), public_api_origin="https://api.example.com")
    assert csp == generate_headers_file(
        script_hashes=frozenset({"abc=="}), public_api_origin="https://api.example.com", csp_extensions=CspExtensions()
    )
    text = csp.decode()
    assert "media-src" not in text
    assert "style-src 'self' 'unsafe-inline';" in text
    assert "font-src 'self' https://fonts.gstatic.com data:;" in text


def test_extensions_add_exactly_the_declared_sources():
    text = generate_headers_file(
        csp_extensions=CspExtensions(
            media_blob=True,
            style_origins=("https://api.fontshare.com",),
            font_origins=("https://cdn.fontshare.com",),
        )
    ).decode()
    assert "media-src 'self' blob:;" in text
    assert "style-src 'self' 'unsafe-inline' https://api.fontshare.com;" in text
    assert "font-src 'self' https://fonts.gstatic.com https://cdn.fontshare.com data:;" in text
    assert "script-src 'self';" in text  # never relaxed


@pytest.mark.parametrize(
    "origin",
    ["http://api.fontshare.com", "https://*.fontshare.com", "https:", "https://cdn.fontshare.com/fonts", "blob:"],
)
def test_extension_origins_must_be_exact_https_origins(origin):
    with pytest.raises(ValueError):
        CspExtensions(font_origins=(origin,))


# --- frontend_engine.build.inline_script_hashes --------------------------------


def _b64sha(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def test_inline_script_hash_is_what_the_browser_hashes_for_nul_and_crlf():
    # TanStack Start's dehydrated router state embeds U+0000; the HTML
    # tokenizer turns it into U+FFFD before CSP hashing, and CRLF into LF.
    html = '<script>$R={i:"__root__\x00"};\r\nboot()</script>'
    assert inline_script_hashes([html]) == frozenset({_b64sha('$R={i:"__root__�"};\nboot()')})


def test_inline_script_hash_is_unchanged_for_ordinary_scripts():
    assert inline_script_hashes(["<script>console.log(1)</script>"]) == frozenset({_b64sha("console.log(1)")})


# --- legal_pages.legal_page_content --------------------------------------------


def test_legal_page_content_is_the_same_wording_the_astro_pages_render():
    truth = _truth()
    content = legal_page_content(truth)
    pages = build_legal_pages(truth)
    assert sorted(content) == ["cookies", "privacy", "terms"]
    assert sorted(pages) == ["src/pages/cookies.astro", "src/pages/privacy.astro", "src/pages/terms.astro"]
    for slug, (title, paragraphs) in content.items():
        page = pages[f"src/pages/{slug}.astro"]
        assert f"<h1>{title}</h1>" in page
        assert all(paragraph.split(":")[0] in page for paragraph in paragraphs)
