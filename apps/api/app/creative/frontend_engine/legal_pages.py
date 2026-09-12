"""Engine-authored legal pages (privacy/terms/cookies) for a generative
build — never AI-authored, for the same "no invented legal facts"
discipline packages/website-generator/src/legal.ts already applies to
the deterministic engine (see that module's own `NOT_PROVIDED`
constant). Guarantees `validate_platform_contract`'s
`missing_legal_page` check always passes for a generative site
regardless of what the AI Frontend Engineer produced, the same way the
deterministic engine's `generateSiteConfig()` always adds all three.

Assumes `src/layouts/Layout.astro` exists with a `{title, description}`
Props interface and a `<slot />` — the AI Frontend Engineer's system
prompt (app.creative.frontend_engine.anthropic_engine) requires it to
create exactly that file, the one fixed structural convention this
engine asks of otherwise-bespoke generated output.
"""

from app.domain.business_config import BusinessConfig

NOT_PROVIDED = "not provided"


def _contact_email(business_config: BusinessConfig) -> str:
    contact = business_config.business_profile.contact
    return contact.email if contact and contact.email else NOT_PROVIDED


def _page(title: str, business_name: str, body_paragraphs: list[str]) -> str:
    paragraphs = "\n".join(f"      <p>{paragraph}</p>" for paragraph in body_paragraphs)
    return f"""---
import Layout from "../layouts/Layout.astro";
---
<Layout title="{title} — {business_name}" description="{title} for {business_name}">
  <main>
    <h1>{title}</h1>
{paragraphs}
  </main>
</Layout>
"""


def build_legal_pages(business_config: BusinessConfig) -> dict[str, str]:
    """Returns {relative_astro_page_path: content} for /privacy, /terms,
    /cookies — written into the workspace by the same engine code path
    that writes the AI's own manifest, at fixed paths the AI's manifest
    is never allowed to touch (workspace.py rejects any AI-submitted
    file whose path collides, since these are always written last)."""
    name = business_config.business_profile.name
    email = _contact_email(business_config)

    return {
        "src/pages/privacy.astro": _page(
            "Privacy Policy",
            name,
            [
                f"{name} respects your privacy. This page describes, in general terms, how information "
                "submitted through this site (for example, via a contact form) is used: to respond to your "
                "enquiry and, where you have given consent, for analytics.",
                f"Contact for privacy questions: {email}.",
            ],
        ),
        "src/pages/terms.astro": _page(
            "Terms of Service",
            name,
            [
                f"These terms govern use of this website by {name}. By using this site you agree to use it "
                "lawfully and not to misuse any contact or lead-capture functionality it provides.",
                f"Questions about these terms can be sent to {email}.",
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
