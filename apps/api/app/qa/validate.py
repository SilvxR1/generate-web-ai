"""validate_site_config — a small, extensible QA layer (Phase 17): a
short, fixed list of structural/content checks on a generated SiteConfig,
run once a draft has already built successfully
(app.publishing.drafts.create_website_draft). Deliberately not an
"enormous QA platform" — every check here is cheap, has no external
dependency, and returns a plain human-readable string; findings are
non-blocking (a human weighs them before approving — see
app.db.models.website_draft.WebsiteDraft's own docstring on why only a
BUILD_FAILED draft is hard-blocked from approval, not a READY one with
issues).
"""

from app.schemas.site_config import SiteConfigPayload


def validate_site_config(site_config: SiteConfigPayload) -> list[str]:
    issues: list[str] = []

    first_page = site_config.pages[0] if site_config.pages else None
    if first_page is None:
        issues.append("Site has no pages.")
        return issues

    block_types = [block.type for block in first_page.blocks]

    if "hero" not in block_types:
        issues.append("Homepage has no hero section.")

    if not site_config.seo.title.strip():
        issues.append("Missing SEO title.")
    if not site_config.seo.description.strip():
        issues.append("Missing SEO description.")

    for block in first_page.blocks:
        if block.type != "testimonials":
            continue
        # Never a fabrication check on content this backend doesn't
        # generate itself (packages/website-generator's own "no invented
        # testimonials" rule is what actually prevents fabrication) — this
        # only flags the presence of an empty section, a plain content gap.
        items = block.content.get("items")
        if not items:
            issues.append("Testimonials section is present but has no reviews to show.")

    if site_config.features and site_config.features.get("contactForm") and "contact" not in block_types:
        issues.append("Contact form is enabled but no contact section is present.")

    return issues
