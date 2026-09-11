"""validate_platform_contract — the P2.7/P2.8 machine-verifiable
PlatformContract: a versioned, engine-agnostic scan over a build's real
static output files (`dict[str, bytes]` — the exact shape
app.publishing.build._read_artifact and app.publishing.publisher's
transient WebsiteArtifact already use for every build, deterministic or
generative alike). Never dictates visual styling — every check here is a
presence/wiring check (a real lead form exists and is wired, no
href="#" dead links, legal pages exist, consent/analytics hooks exist,
SEO metadata is non-empty), never a check on color/font/layout, so a
bespoke generative site and a deterministic block-composed site can look
completely different while satisfying the exact same contract.

BLOCKING findings gate WebsiteDraftStatus the same way a build failure
already does (see app.domain.enums.PlatformContractSeverity's own
docstring) — P2.8's "must never reach an approved/publishable state with
decorative dead CTAs" is enforced here, not only by convention.
ADVISORY findings are visible to a human but never block, mirroring
app.qa.validate's existing `validation_issues` convention.

Deliberately regex/string based, not a full HTML parser — every check is
a presence/pattern match over already-trusted, already-built platform
output (not untrusted user input), and this mirrors
app.publishing.build's own `_INLINE_SCRIPT_PATTERN` precedent for the
same kind of lightweight HTML scanning in this codebase.
"""

import re

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadSource, PlatformContractSeverity

PLATFORM_CONTRACT_VERSION = "1.0.0"

_HREF_HASH_ONLY = re.compile(r'href\s*=\s*"#"')
_HREF_ANCHOR = re.compile(r'href\s*=\s*"#([\w-]+)"')
_ID_ATTR = re.compile(r'\bid\s*=\s*"([\w-]+)"')
_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_META_DESCRIPTION = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.IGNORECASE)
_VIEWPORT_META = re.compile(r'<meta\s+name="viewport"', re.IGNORECASE)
_LEAD_FORM_MARKER = re.compile(r'data-gwa-lead-form|data-platform="lead-form"')
_LEAD_WIRING_MARKER = re.compile(r"submitLead|lead\.submitted")
_CONSENT_MARKER = re.compile(r"gwaConsent")
_ANALYTICS_MARKER = re.compile(r"gwaAnalytics")
_WHATSAPP_LINK = re.compile(r"wa\.me/")
_ANIMATION_RULE = re.compile(r"@keyframes|animation\s*:")
_REDUCED_MOTION_QUERY = re.compile(r"prefers-reduced-motion")

_LEGAL_SLUGS = ("privacy", "terms", "cookies")


class PlatformContractFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    severity: PlatformContractSeverity
    message: str
    location: str | None = None


class PlatformContractResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = PLATFORM_CONTRACT_VERSION
    findings: list[PlatformContractFinding] = Field(default_factory=list)

    @property
    def blocking_violations(self) -> list[PlatformContractFinding]:
        return [f for f in self.findings if f.severity is PlatformContractSeverity.BLOCKING]

    @property
    def advisory_findings(self) -> list[PlatformContractFinding]:
        return [f for f in self.findings if f.severity is PlatformContractSeverity.ADVISORY]

    @property
    def passed(self) -> bool:
        return not self.blocking_violations


def _html_files(files: dict[str, bytes]) -> dict[str, str]:
    return {path: content.decode("utf-8", errors="ignore") for path, content in files.items() if path.endswith(".html")}


def _script_text(files: dict[str, bytes]) -> str:
    return "\n".join(
        content.decode("utf-8", errors="ignore") for path, content in files.items() if path.endswith((".js", ".css"))
    )


def _check_dead_ctas(html_files: dict[str, str], all_text: str) -> list[PlatformContractFinding]:
    findings: list[PlatformContractFinding] = []
    all_ids = set(_ID_ATTR.findall(all_text))
    for path, html in html_files.items():
        if _HREF_HASH_ONLY.search(html):
            findings.append(
                PlatformContractFinding(
                    rule="dead_cta_href_hash",
                    severity=PlatformContractSeverity.BLOCKING,
                    message='A CTA has href="#" with no defined behavior.',
                    location=path,
                )
            )
        for match in _HREF_ANCHOR.finditer(html):
            target = match.group(1)
            if target not in all_ids:
                findings.append(
                    PlatformContractFinding(
                        rule="broken_anchor_target",
                        severity=PlatformContractSeverity.BLOCKING,
                        message=(
                            f'An anchor targets "#{target}", which has no matching id="{target}" '
                            "anywhere in the build."
                        ),
                        location=path,
                    )
                )
    return findings


def _check_lead_capture(
    html_files: dict[str, str], script_text: str, *, business_config: BusinessConfig
) -> list[PlatformContractFinding]:
    lead_capture_expected = business_config.automation.lead_capture or (
        LeadSource.WEBSITE_FORM in business_config.lead_management.sources
    )
    if not lead_capture_expected:
        return []

    has_form = any(_LEAD_FORM_MARKER.search(html) for html in html_files.values())
    if not has_form:
        return [
            PlatformContractFinding(
                rule="missing_lead_form",
                severity=PlatformContractSeverity.BLOCKING,
                message="Lead capture is enabled for this business, but no build output contains a lead form "
                "(data-gwa-lead-form).",
            )
        ]

    has_action = any('form' in html and 'action="http' in html for html in html_files.values())
    # Astro inlines a small enough client <script> directly into the
    # HTML rather than always externalizing it to a .js chunk (verified
    # against a real generative build) — the wiring evidence can live in
    # either place, so both html_files and script_text must be searched.
    combined_html = "\n".join(html_files.values())
    is_wired = (
        bool(_LEAD_WIRING_MARKER.search(script_text)) or bool(_LEAD_WIRING_MARKER.search(combined_html)) or has_action
    )
    if not is_wired:
        return [
            PlatformContractFinding(
                rule="disconnected_lead_form",
                severity=PlatformContractSeverity.BLOCKING,
                message="A lead form exists but is wired to neither the platform lead-submission SDK "
                "(submitLead/lead.submitted) nor a direct n8n webhook action.",
            )
        ]
    return []


def _check_legal_pages(files: dict[str, bytes]) -> list[PlatformContractFinding]:
    findings = []
    for slug in _LEGAL_SLUGS:
        if f"{slug}/index.html" not in files and f"{slug}.html" not in files:
            findings.append(
                PlatformContractFinding(
                    rule="missing_legal_page",
                    severity=PlatformContractSeverity.BLOCKING,
                    message=f"No /{slug} legal page found in the build output.",
                )
            )
    return findings


def _check_consent_and_analytics(all_text: str, script_text: str) -> list[PlatformContractFinding]:
    findings = []
    if not (_CONSENT_MARKER.search(all_text) or _CONSENT_MARKER.search(script_text)):
        findings.append(
            PlatformContractFinding(
                rule="missing_consent_mechanism",
                severity=PlatformContractSeverity.BLOCKING,
                message="No consent mechanism (gwaConsent) found in the build output.",
            )
        )
    if not (_ANALYTICS_MARKER.search(all_text) or _ANALYTICS_MARKER.search(script_text)):
        findings.append(
            PlatformContractFinding(
                rule="missing_analytics_beacon",
                severity=PlatformContractSeverity.ADVISORY,
                message="No analytics beacon (gwaAnalytics) found in the build output.",
            )
        )
    return findings


def _check_whatsapp(all_text: str, *, business_config: BusinessConfig) -> list[PlatformContractFinding]:
    whatsapp = business_config.whatsapp
    if not whatsapp or not whatsapp.enabled:
        return []
    if not _WHATSAPP_LINK.search(all_text):
        return [
            PlatformContractFinding(
                rule="missing_whatsapp_link",
                severity=PlatformContractSeverity.BLOCKING,
                message="WhatsApp is configured for this business, but no wa.me link was found in the build output.",
            )
        ]
    return []


def _check_seo(html_files: dict[str, str]) -> list[PlatformContractFinding]:
    findings = []
    for path, html in html_files.items():
        title_match = _TITLE_TAG.search(html)
        if not title_match or not title_match.group(1).strip():
            findings.append(
                PlatformContractFinding(
                    rule="missing_seo_title",
                    severity=PlatformContractSeverity.BLOCKING,
                    message="Page has no non-empty <title>.",
                    location=path,
                )
            )
        description_match = _META_DESCRIPTION.search(html)
        if not description_match or not description_match.group(1).strip():
            findings.append(
                PlatformContractFinding(
                    rule="missing_seo_description",
                    severity=PlatformContractSeverity.BLOCKING,
                    message="Page has no non-empty <meta name=\"description\">.",
                    location=path,
                )
            )
        if not _VIEWPORT_META.search(html):
            findings.append(
                PlatformContractFinding(
                    rule="missing_viewport_meta",
                    severity=PlatformContractSeverity.ADVISORY,
                    message="Page has no <meta name=\"viewport\"> tag.",
                    location=path,
                )
            )
    return findings


def _check_reduced_motion(script_text: str) -> list[PlatformContractFinding]:
    if _ANIMATION_RULE.search(script_text) and not _REDUCED_MOTION_QUERY.search(script_text):
        return [
            PlatformContractFinding(
                rule="animation_without_reduced_motion_guard",
                severity=PlatformContractSeverity.ADVISORY,
                message="The build defines CSS animation/@keyframes without a prefers-reduced-motion guard "
                "anywhere in its stylesheets.",
            )
        ]
    return []


def validate_platform_contract(files: dict[str, bytes], *, business_config: BusinessConfig) -> PlatformContractResult:
    """Runs the full PlatformContract scan over one build's output files
    — called on both engines' output (app.publishing.drafts for
    DETERMINISTIC, app.creative.frontend_engine for GENERATIVE), so a
    BLOCKING violation gates draft approval identically regardless of
    which engine produced the build. Never inspects colors/fonts/layout —
    every rule is a structural/wiring presence check."""
    html_files = _html_files(files)
    script_text = _script_text(files)
    all_text = "\n".join(html_files.values())

    findings: list[PlatformContractFinding] = []
    findings += _check_dead_ctas(html_files, all_text)
    findings += _check_lead_capture(html_files, script_text, business_config=business_config)
    findings += _check_legal_pages(files)
    findings += _check_consent_and_analytics(all_text, script_text)
    findings += _check_whatsapp(all_text, business_config=business_config)
    findings += _check_seo(html_files)
    findings += _check_reduced_motion(script_text)

    return PlatformContractResult(findings=findings)
