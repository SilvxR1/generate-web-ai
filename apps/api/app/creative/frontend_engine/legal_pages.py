"""Engine-authored legal pages (privacy/terms/cookies) for a generative
build — never AI-authored, for the same "no invented legal facts"
discipline packages/website-generator/src/legal.ts already applies to
the deterministic engine (see that module's own `NOT_PROVIDED`
constant). Guarantees `validate_platform_contract`'s
`missing_legal_page` check always passes for a generative site
regardless of what the AI Frontend Engineer produced, the same way the
deterministic engine's `generateSiteConfig()` always adds all three.

v0.2 R1: rendered from BusinessTruth.legal — legal name, registered
address, registration number, tax ID, privacy contact and data processors
(parity with legal.ts). Anything missing is stated as "not provided";
the trading name is never substituted for the legal name. Every value is
HTML-escaped and Astro-expression-escaped, since it is business-supplied
text written into an .astro template.

Assumes `src/layouts/Layout.astro` exists with a `{title, description}`
Props interface and a `<slot />` — the AI Frontend Engineer's system
prompt (app.creative.frontend_engine.anthropic_engine) requires it to
create exactly that file, the one fixed structural convention this
engine asks of otherwise-bespoke generated output.
"""

import html

from app.domain.business_truth import AddressTruth, BusinessTruth

NOT_PROVIDED = "not provided"


def _text(value: str) -> str:
    """Safe inside an Astro template: HTML-escaped, and `{`/`}` escaped so
    business text can never become an Astro expression."""
    return html.escape(value, quote=True).replace("{", "&#123;").replace("}", "&#125;")


def _or_missing(value: str | None) -> str:
    return value if value else NOT_PROVIDED


def _address(address: AddressTruth | None) -> str:
    if address is None:
        return NOT_PROVIDED
    parts = [address.street_address, address.locality, address.region, address.postal_code, address.country]
    return ", ".join(part for part in parts if part and part.strip())


def _page(title: str, business_name: str, body_paragraphs: list[str]) -> str:
    paragraphs = "\n".join(f"      <p>{_text(paragraph)}</p>" for paragraph in body_paragraphs)
    title_attr = _text(f"{title} — {business_name}")
    description_attr = _text(f"{title} for {business_name}")
    return f"""---
import Layout from "../layouts/Layout.astro";
---
<Layout title="{title_attr}" description="{description_attr}">
  <main>
    <h1>{_text(title)}</h1>
{paragraphs}
  </main>
</Layout>
"""


def build_legal_pages(business_truth: BusinessTruth) -> dict[str, str]:
    """Returns {relative_astro_page_path: content} for /privacy, /terms,
    /cookies — written into the workspace by the same engine code path
    that writes the AI's own manifest, at fixed paths the AI's manifest
    is never allowed to touch (workspace.py rejects any AI-submitted
    file whose path collides, since these are always written last)."""
    name = business_truth.identity.name
    legal = business_truth.legal
    privacy_email = legal.privacy_contact_email or business_truth.contact.email or NOT_PROVIDED
    processors = (
        ", ".join(legal.data_processors)
        if legal.data_processors
        else "No third-party data processors have been listed for this business."
    )

    return {
        "src/pages/privacy.astro": _page(
            "Privacy Policy",
            name,
            [
                f"This website is operated by {name}.",
                f"Legal name: {_or_missing(legal.legal_name)}.",
                f"Registered address: {_address(legal.registered_address)}.",
                f"Registration number: {_or_missing(legal.registration_number)}.",
                f"Tax ID: {_or_missing(legal.tax_id)}.",
                "Information submitted through this site (for example, via a contact form) is used to respond "
                "to your enquiry and, where you have given consent, for analytics.",
                f"Third parties we work with: {processors}",
                f"Contact for privacy questions: {privacy_email}.",
            ],
        ),
        "src/pages/terms.astro": _page(
            "Terms of Service",
            name,
            [
                f"These terms govern use of this website operated by {name} "
                f"(legal name: {_or_missing(legal.legal_name)}). By using this site you agree to use it "
                "lawfully and not to misuse any contact or lead-capture functionality it provides.",
                f"Questions about these terms can be sent to {privacy_email}.",
            ],
        ),
        "src/pages/cookies.astro": _page(
            "Cookie Policy",
            name,
            [
                "Necessary cookies are always on. Everything else (analytics, marketing, preferences) stays "
                "off unless you explicitly choose to allow it via the cookie banner.",
            ],
        ),
    }
