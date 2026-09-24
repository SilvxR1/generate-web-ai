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

import json
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadSource, PlatformContractSeverity
from app.publishing.public_origin import canonical_public_origin, public_origin_problem

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

# A8.3.4-P0: the runtime config the built site's browser scripts read their
# API origin from. Deterministic builds render `lead-submission-config`
# (apps/site-builder LeadSubmission.astro); generative builds get an
# injected `platform-config` (app.creative.frontend_engine.build).
_RUNTIME_CONFIG = re.compile(
    r'<script[^>]*\bid="(?:lead-submission-config|platform-config)"[^>]*>(.*?)</script>', re.DOTALL
)
# Analytics.astro's `define:vars` renders the origin as a JS string literal.
_ANALYTICS_API_BASE = re.compile(r'\bapiBaseUrl\s*=\s*"([^"]*)"')
_DIRECT_FORM_ACTION = re.compile(r'<form[^>]*\baction="https?://', re.IGNORECASE)
# A8.3.4-P0.2: the policies the browser actually enforces — Cloudflare Pages'
# `_headers` lines and any `<meta http-equiv>` CSP the markup declares.
_HEADERS_CSP_LINE = re.compile(r"^\s*Content-Security-Policy\s*:(.*)$", re.IGNORECASE | re.MULTILINE)
_META_CSP = re.compile(
    r'<meta[^>]*\bhttp-equiv\s*=\s*"Content-Security-Policy"[^>]*\bcontent\s*=\s*"([^"]*)"', re.IGNORECASE
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


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
                            f'An anchor targets "#{target}", which has no matching id="{target}" anywhere in the build.'
                        ),
                        location=path,
                    )
                )
    return findings


def _check_lead_capture(
    html_files: dict[str, str], script_text: str, *, business_config: BusinessConfig
) -> list[PlatformContractFinding]:
    if not _lead_capture_expected(business_config):
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

    has_action = any("form" in html and 'action="http' in html for html in html_files.values())
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


def _runtime_configs(html_files: dict[str, str]) -> list[dict]:
    configs = []
    for html in html_files.values():
        for raw in _RUNTIME_CONFIG.findall(html):
            try:
                parsed = json.loads(raw)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                configs.append(parsed)
    return configs


def _lead_capture_expected(business_config: BusinessConfig) -> bool:
    return business_config.automation.lead_capture or (
        LeadSource.WEBSITE_FORM in business_config.lead_management.sources
    )


def _check_lead_endpoint(
    html_files: dict[str, str], *, business_config: BusinessConfig
) -> list[PlatformContractFinding]:
    """A8.3.4-P0: `disconnected_lead_form` only proves a submit script
    exists; this proves the rendered form has somewhere real to submit to.
    With lead capture expected and a lead form in the build, at least one
    rendered runtime config must carry the business id and a valid public
    API origin — otherwise the form silently drops every lead. A form wired
    directly to an n8n webhook (`action="http..."`) needs no API origin."""
    if not _lead_capture_expected(business_config):
        return []
    if not any(_LEAD_FORM_MARKER.search(html) for html in html_files.values()):
        return []  # missing_lead_form already reports this case
    if any(_DIRECT_FORM_ACTION.search(html) for html in html_files.values()):
        return []

    problems = []
    for config in _runtime_configs(html_files):
        problem = public_origin_problem(config.get("apiBaseUrl"))
        if problem is None and config.get("businessId"):
            return []
        problems.append(problem or "the business id is missing")
    reason = problems[0] if problems else "no runtime lead-submission config was rendered"
    return [
        PlatformContractFinding(
            rule="lead_endpoint_unconfigured",
            severity=PlatformContractSeverity.BLOCKING,
            message=f"The lead form has no usable submission endpoint ({reason}), so every lead would be lost.",
        )
    ]


def _check_analytics_endpoint(
    html_files: dict[str, str], all_text: str, script_text: str
) -> list[PlatformContractFinding]:
    """ADVISORY (A8.3.4-P0 decision): the analytics beacon has no
    per-business on/off switch — it is always part of the build — so a
    missing origin can't be a blocking "enabled feature doesn't work"
    finding without also blocking sites that simply don't capture leads.
    Lead capture, which is configurable, is the blocking check above."""
    if not (_ANALYTICS_MARKER.search(all_text) or _ANALYTICS_MARKER.search(script_text)):
        return []
    origins = _ANALYTICS_API_BASE.findall(all_text) + [
        str(config.get("apiBaseUrl") or "") for config in _runtime_configs(html_files)
    ]
    if any(public_origin_problem(origin) is None for origin in origins):
        return []
    return [
        PlatformContractFinding(
            rule="analytics_endpoint_unconfigured",
            severity=PlatformContractSeverity.ADVISORY,
            message="The analytics beacon has no usable public API origin, so no analytics events would be sent.",
        )
    ]


def _effective_policies(files: dict[str, bytes], html_files: dict[str, str]) -> list[str]:
    policies = [m.strip() for m in _HEADERS_CSP_LINE.findall(files.get("_headers", b"").decode("utf-8", "ignore"))]
    for html in html_files.values():
        policies += [m.strip() for m in _META_CSP.findall(html)]
    return [p for p in policies if p]


def _connect_sources(policy: str) -> list[str] | None:
    """The source list governing fetch() under one policy: `connect-src`,
    else `default-src`, else None (unrestricted). Per CSP3, directive
    names are case-insensitive and only a directive's first occurrence
    counts."""
    directives: dict[str, list[str]] = {}
    for part in policy.split(";"):
        tokens = part.split()
        if tokens:
            directives.setdefault(tokens[0].lower(), tokens[1:])
    return directives.get("connect-src", directives.get("default-src"))


def _source_allows(source: str, origin: str) -> bool:
    """CSP3 source-expression matching for a bare `scheme://host[:port]`
    target. `'self'` never matches: the site is served from its own
    domain, never from the API's. Hosts compare exactly (a `*.` prefix
    matches strict subdomains only), so `https://api.example.com.evil.test`
    never matches `https://api.example.com`. No DNS resolution."""
    target = urlsplit(origin)
    target_port = target.port or _DEFAULT_PORTS[target.scheme]
    source = source.lower()
    if source == "*":
        return target.scheme in _DEFAULT_PORTS
    if source.startswith("'"):
        return False
    if re.fullmatch(r"[a-z][a-z0-9+.-]*:", source):  # scheme-source, e.g. `https:`
        return source[:-1] == target.scheme or (source == "http:" and target.scheme == "https")
    match = re.fullmatch(r"(?:([a-z][a-z0-9+.-]*)://)?(\*|\*\.[^/:]+|[^/:*]+)(?::(\d+|\*))?(/.*)?", source)
    if not match:
        return False
    scheme, host, port, path = match.groups()
    if scheme and not (scheme == target.scheme or (scheme == "http" and target.scheme == "https")):
        return False
    if host == "*":
        pass
    elif host.startswith("*."):
        if not (target.hostname or "").endswith(host[1:]):
            return False
    elif host != target.hostname:
        return False
    if port != "*":
        allowed_port = int(port) if port else _DEFAULT_PORTS.get(scheme or target.scheme)
        if allowed_port != target_port and not (port is None and scheme == "http" and target_port == 443):
            return False
    # A path-restricted source can't be proven to cover every endpoint the
    # scripts call; treat anything narrower than the whole origin as a miss.
    return path in (None, "/")


def _check_public_api_csp(
    files: dict[str, bytes], html_files: dict[str, str], all_text: str
) -> list[PlatformContractFinding]:
    """A8.3.4-P0.2: every valid public API origin the rendered runtime
    config tells the browser scripts to call (lead form, analytics beacon)
    must be allowed by EVERY effective CSP's connect-src — the browser
    enforces all of them, and a single miss makes fetch() fail before any
    request leaves the page. Unusable origins are reported by
    lead_endpoint_unconfigured / analytics_endpoint_unconfigured instead;
    a build with no API origin or no CSP produces no finding here."""
    rendered = _ANALYTICS_API_BASE.findall(all_text) + [
        str(config.get("apiBaseUrl") or "") for config in _runtime_configs(html_files)
    ]
    origins = sorted({o for o in map(canonical_public_origin, rendered) if o})
    findings = []
    for origin in origins:
        for policy in _effective_policies(files, html_files):
            sources = _connect_sources(policy)
            if sources is None or any(_source_allows(source, origin) for source in sources):
                continue
            findings.append(
                PlatformContractFinding(
                    rule="public_api_csp_disconnected",
                    severity=PlatformContractSeverity.BLOCKING,
                    message=(
                        f"The site's scripts call {origin}, but its Content-Security-Policy connect-src "
                        f"({' '.join(sources) or 'empty'}) does not allow it, so the browser would block "
                        "every lead submission and analytics event."
                    ),
                )
            )
            break
    return findings


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
                    message='Page has no non-empty <meta name="description">.',
                    location=path,
                )
            )
        if not _VIEWPORT_META.search(html):
            findings.append(
                PlatformContractFinding(
                    rule="missing_viewport_meta",
                    severity=PlatformContractSeverity.ADVISORY,
                    message='Page has no <meta name="viewport"> tag.',
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
    findings += _check_lead_endpoint(html_files, business_config=business_config)
    findings += _check_analytics_endpoint(html_files, all_text, script_text)
    findings += _check_public_api_csp(files, html_files, all_text)
    findings += _check_legal_pages(files)
    findings += _check_consent_and_analytics(all_text, script_text)
    findings += _check_whatsapp(all_text, business_config=business_config)
    findings += _check_seo(html_files)
    findings += _check_reduced_motion(script_text)

    return PlatformContractResult(findings=findings)
