"""Platform integration content for React-based exported sites (H2).

Everything here is GWA platform output — identical for every export of a
React/TanStack family, parameterised only by BusinessTruth, the site
context, the discovered FormMapping and reviewed overlay decisions:

- the Platform SDK (verbatim, the file every generative site receives);
- business facts module + truth-only JSON-LD;
- legal content/components/routes (app.creative.frontend_engine.legal_pages
  wording, es/en);
- the consent-banner theme (only through --gwa-consent-* variables);
- the LEAD TRANSPORT: a module that replaces an export's server function
  with the same call shape, reading the form's own fields and sending them
  through the SDK (every field kept, submission id reused across retries,
  honeypot + timing, failure raised so the form's own error state shows);
- the owned Open Graph image (a deterministic crop of an export frame);
- launch-readiness findings (owner/legal input still needed).
"""

import io
import json
from pathlib import Path

from PIL import Image

import app.creative.frontend_engine as frontend_engine
from app.creative.frontend_engine.legal_pages import legal_owner_input_required, legal_page_content
from app.creative.source_adapter.forms import FormMapping
from app.domain.business_truth import BusinessTruth

PLATFORM_SDK_TEMPLATE = Path(frontend_engine.__file__).parent / "templates" / "platform_sdk.ts"

# OFL-licensed families GWA self-hosts from @fontsource (exact versions,
# licence verified on the public registry: "license": "OFL-1.1").
SELF_HOSTED_FONTS: dict[str, tuple[str, str]] = {
    "Inter Tight": ("@fontsource/inter-tight", "5.3.0"),
    "IBM Plex Mono": ("@fontsource/ibm-plex-mono", "5.3.0"),
    "Inter": ("@fontsource/inter", "5.3.0"),
    "Fraunces": ("@fontsource/fraunces", "5.3.0"),
}

# Third-party services a family's CSP policy allows, disclosed on /cookies.
THIRD_PARTY_DISCLOSURES: dict[str, dict[str, str]] = {
    "fontshare": {
        "es": "Fontshare (Indian Type Foundry) sirve tipografías desde sus servidores (api.fontshare.com, "
        "cdn.fontshare.com); al cargar la página, tu navegador les envía tu dirección IP. No se usa para analítica.",
        "en": "Fontshare (Indian Type Foundry) serves typefaces from its servers (api.fontshare.com, "
        "cdn.fontshare.com); loading the page sends your IP address to them. It is not used for analytics.",
    }
}

JSON_LD_TYPES = {
    "home_renovation": "HomeAndConstructionBusiness",
    "real_estate": "RealEstateAgent",
    "clinic": "MedicalClinic",
    "restaurant": "Restaurant",
    "hotel": "Hotel",
    "agency": "ProfessionalService",
    "b2b_services": "ProfessionalService",
    "ecommerce": "Store",
}

_TEXT = {
    "es": {
        "privacy": "Privacidad",
        "terms": "Aviso legal",
        "cookies": "Cookies",
        "prefs": "Preferencias de cookies",
        "back": "Volver al inicio",
        "honeypot": "No rellenar",
        "desc": "{title} de {name}",
    },
    "en": {
        "privacy": "Privacy",
        "terms": "Legal notice",
        "cookies": "Cookies",
        "prefs": "Cookie preferences",
        "back": "Back to home",
        "honeypot": "Leave empty",
        "desc": "{title} for {name}",
    },
}
OG_SIZE = (1200, 630)


def text(locale: str, key: str) -> str:
    return _TEXT.get(locale, _TEXT["en"])[key]


def platform_sdk() -> str:
    return PLATFORM_SDK_TEMPLATE.read_text(encoding="utf-8")


def json_ld(truth: BusinessTruth, origin: str) -> dict:
    """schema.org data built ONLY from BusinessTruth — no rating, review,
    price, founding date or count is ever emitted; absent facts are absent."""
    data: dict = {
        "@context": "https://schema.org",
        "@type": JSON_LD_TYPES.get(truth.identity.industry, "LocalBusiness"),
        "name": truth.identity.name,
        "url": f"{origin}/",
        "areaServed": [
            {"@type": "City", "name": area} for area in [truth.location.city, *truth.location.service_area] if area
        ],
        "makesOffer": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": s.name}} for s in truth.services],
    }
    contact = truth.contact
    if contact.phone:
        data["telephone"] = contact.phone
    if contact.email:
        data["email"] = contact.email
    if contact.address is not None:
        data["address"] = {
            "@type": "PostalAddress",
            "streetAddress": contact.address.street_address,
            "addressLocality": contact.address.locality,
            **({"postalCode": contact.address.postal_code} if contact.address.postal_code else {}),
            "addressCountry": contact.address.country,
        }
    if truth.logo is not None:
        data["logo"] = truth.logo.url
    return data


def business_module(truth: BusinessTruth, origin: str) -> str:
    logo = None if truth.logo is None else {"src": truth.logo.url, "alt": truth.logo.alt_text or ""}
    # `</` can never close the JSON-LD <script> the string is embedded in.
    ld = json.dumps(json_ld(truth, origin), ensure_ascii=False).replace("</", "<\\\\/")
    return (
        "/**\n"
        " * GWA platform: business facts from BusinessTruth. Generated on every\n"
        " * build by app.creative.source_adapter — never edit by hand.\n"
        " */\n"
        "export const BUSINESS = {\n"
        f"  name: {json.dumps(truth.identity.name, ensure_ascii=False)},\n"
        f"  city: {json.dumps(truth.location.city, ensure_ascii=False)},\n"
        f"  logo: {json.dumps(logo, ensure_ascii=False)} as null | {{ src: string; alt: string }},\n"
        f"  siteOrigin: {json.dumps(origin)},\n"
        "};\n\n"
        f"export const SITE_JSONLD = {json.dumps(ld, ensure_ascii=False)};\n"
    )


def legal_content_json(truth: BusinessTruth, locale: str, third_parties: tuple[str, ...]) -> str:
    name = truth.identity.name
    pages = {
        slug: {
            "title": title,
            "metaTitle": f"{title} — {name}",
            "metaDescription": text(locale, "desc").format(title=title, name=name),
            "paragraphs": paragraphs,
        }
        for slug, (title, paragraphs) in legal_page_content(truth, locale=locale, third_parties=third_parties).items()
    }
    return json.dumps({"businessName": name, "lang": locale, "pages": pages}, ensure_ascii=False, indent=2) + "\n"


def legal_links_tsx(locale: str, nav_class: str | None, link_class: str | None) -> str:
    nav = f' className="{nav_class}"' if nav_class else ""
    link = f' className="{link_class}"' if link_class else ""
    entries = "".join(
        f'      <a{link} href="/{slug}">\n        {text(locale, slug)}\n      </a>\n'
        for slug in ("privacy", "terms", "cookies")
    )
    return (
        "/**\n"
        " * GWA platform: legal routes and cookie preferences.\n"
        " * `data-open-consent-preferences` reopens the platform consent banner.\n"
        " */\n"
        "export function LegalLinks() {\n"
        "  return (\n"
        f'    <nav aria-label="Legal"{nav}>\n'
        f"{entries}"
        f'      <button{link} data-open-consent-preferences="" type="button">\n'
        f"        {text(locale, 'prefs')}\n"
        "      </button>\n"
        "    </nav>\n"
        "  );\n"
        "}\n"
    )


LEGAL_HEAD_TS = """export type LegalSlug = "privacy" | "terms" | "cookies";

export function legalHead(slug: LegalSlug) {
  const page = legal.pages[slug];
  return {
    meta: [{ title: page.metaTitle }, { name: "description", content: page.metaDescription }],
    links: [{ rel: "canonical", href: `${BUSINESS.siteOrigin}/${slug}` }],
  };
}
"""

LEGAL_PAGE_IMPORTS = (
    'import { BUSINESS } from "./business";\nimport legal from "./legal-content.json";\n'
    'import { LegalLinks } from "./legal-links";\n'
)


def default_legal_page_tsx(locale: str) -> str:
    """A neutral legal page for designs without a reviewed presentation:
    semantic HTML that inherits the site's global typography and colours."""
    return (
        LEGAL_PAGE_IMPORTS
        + "\n/** GWA platform legal page (content: BusinessTruth; wording needs owner/legal review). */\n"
        + LEGAL_HEAD_TS
        + "\nexport function LegalPage({ slug }: { slug: LegalSlug }) {\n"
        "  const page = legal.pages[slug];\n"
        "  return (\n"
        '    <main style={{ margin: "0 auto", maxWidth: "72ch", padding: "4rem 1.25rem" }}>\n'
        "      <p>\n"
        f'        <a href="/">{{legal.businessName}}</a> · <a href="/">{text(locale, "back")}</a>\n'
        "      </p>\n"
        "      <article lang={legal.lang}>\n"
        "        <h1>{page.title}</h1>\n"
        "        {page.paragraphs.map((paragraph) => (\n"
        "          <p key={paragraph}>{paragraph}</p>\n"
        "        ))}\n"
        "      </article>\n"
        '      <footer style={{ marginTop: "3rem" }}>\n'
        "        <LegalLinks />\n"
        "      </footer>\n"
        "    </main>\n"
        "  );\n"
        "}\n"
    )


def legal_route_tsx(slug: str, component: str, page_module: str) -> str:
    return (
        'import { createFileRoute } from "@tanstack/react-router";\n\n'
        f'import {{ LegalPage, legalHead }} from "{page_module}";\n\n'
        "// GWA platform legal route (content from BusinessTruth).\n"
        f'export const Route = createFileRoute("/{slug}")({{\n'
        f'  head: () => legalHead("{slug}"),\n'
        f"  component: {component},\n"
        "});\n\n"
        f"function {component}() {{\n"
        f'  return <LegalPage slug="{slug}" />;\n'
        "}\n"
    )


def consent_theme_ts(theme: dict[str, str]) -> str:
    body = "".join(f"  {json.dumps(k)}: {json.dumps(v)},\n" for k, v in theme.items())
    return (
        'import type { CSSProperties } from "react";\n\n'
        "/**\n"
        " * GWA platform consent banner, themed ONLY through its documented\n"
        " * --gwa-consent-* custom properties, pointed at the site's own tokens.\n"
        " * Set on <html> so no stylesheet targets the banner.\n"
        " */\n"
        f"export const GWA_CONSENT_THEME = {{\n{body}}} as CSSProperties;\n"
    )


def honeypot_jsx(locale: str, indent: str) -> str:
    return (
        f"{indent}{{/* GWA platform: spam honeypot — off-screen, never filled by a person. */}}\n"
        f'{indent}<div aria-hidden="true" style={{{{ height: 1, left: -10000, overflow: "hidden", '
        'position: "absolute", width: 1 }}>\n'
        f'{indent}  <label htmlFor="hp_field">{text(locale, "honeypot")}</label>\n'
        f'{indent}  <input autoComplete="off" id="hp_field" name="hp_field" tabIndex={{-1}} type="text" />\n'
        f"{indent}</div>\n"
    )


def lead_transport_ts(
    mapping: FormMapping, *, symbol: str, type_names: list[str], form_key: str, sdk_module: str
) -> str:
    fields = [{"name": f.name, "role": f.role, "key": f.key, "label": f.label} for f in mapping.fields]
    type_body = "".join(f"  {json.dumps(f.name)}: string;\n" for f in mapping.fields)
    types = "".join(
        f"export type {name} = {{\n  [field: string]: string;\n{type_body}}};\n\n" for name in sorted(type_names)
    )
    fields_json = json.dumps(fields, ensure_ascii=False, indent=2)
    return f"""/**
 * GWA platform lead transport for {mapping.form_id}.
 *
 * Generated from the form's FormMapping. It replaces the export's server
 * function `{symbol}` with the same call shape, so the form's own code,
 * validation and states are unchanged. The values sent are the form's own
 * fields as the visitor filled them (read from the form element): core
 * fields to the Lead API's fields, the rest as labelled details. A failed
 * submission throws, so the form shows its own error state; a retry after
 * a failure reuses the submission id, so the lead is stored at most once.
 */
import {{ HONEYPOT_FIELD_NAME, TIMING_FIELD_NAME, submitLead as submitToGwa }} from "{sdk_module}";

{types}const FORM_SELECTOR = 'form[data-gwa-lead-form="{form_key}"]';
const FIELDS: {{ name: string; role: string; key: string; label: string }}[] = {fields_json};

// When the page became interactive in the visitor's browser (the Lead API's
// spam timing check) — never the prerender time.
const renderedAt = typeof window === "undefined" ? "" : new Date().toISOString();
let submissionId = "";

function readForm(fallback: Record<string, unknown>): {{ form: HTMLFormElement | null; values: Map<string, string> }} {{
  const form = typeof document === "undefined" ? null : document.querySelector<HTMLFormElement>(FORM_SELECTOR);
  const values = new Map<string, string>();
  for (const field of FIELDS) {{
    let value = "";
    const element = form?.elements.namedItem(field.name);
    if (element instanceof HTMLInputElement && element.type === "checkbox") {{
      value = element.checked ? "true" : "";
    }} else if (element instanceof HTMLSelectElement) {{
      value = element.selectedOptions[0]?.text.trim() || element.value;
    }} else if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {{
      value = element.value;
    }} else if (fallback[field.name] != null) {{
      value = String(fallback[field.name]);
    }}
    values.set(field.name, value.trim());
  }}
  return {{ form, values }};
}}

export async function {symbol}({{ data }}: {{ data: Record<string, unknown> }}): Promise<{{ received: true }}> {{
  const {{ form, values }} = readForm(data ?? {{}});
  const honeypot = form?.elements.namedItem(HONEYPOT_FIELD_NAME);
  const fields: Record<string, string> = {{
    [HONEYPOT_FIELD_NAME]: honeypot instanceof HTMLInputElement ? honeypot.value : "",
    [TIMING_FIELD_NAME]: renderedAt,
  }};
  const details: {{ key: string; label: string; value: string }}[] = [];
  let subject = "";
  for (const field of FIELDS) {{
    const value = values.get(field.name) ?? "";
    if (field.role === "detail" || field.role === "service") {{
      details.push({{ key: field.key, label: field.label, value }});
      if (field.role === "service") subject = value;
    }} else {{
      fields[field.role] = value;
    }}
  }}
  if (!submissionId) {{
    submissionId = globalThis.crypto?.randomUUID?.() ?? "";
  }}
  const sent = await submitToGwa(fields, subject, {{ details, submissionId: submissionId || undefined }});
  if (!sent) {{
    throw new Error("The lead was not accepted.");
  }}
  submissionId = "";
  return {{ received: true }};
}}
"""


def derive_og_image(source: bytes) -> bytes:
    """The export's own frame, center-cropped to 1200x630 JPEG — fixed crop,
    quality and no metadata, so identical input gives identical bytes. No
    text is drawn, so no font file is ever needed."""
    with Image.open(io.BytesIO(source)) as image_file:
        image = image_file.convert("RGB")
    width, height = image.size
    ratio = OG_SIZE[0] / OG_SIZE[1]
    crop_width = min(width, round(height * ratio))
    crop_height = round(crop_width / ratio)
    left, top = (width - crop_width) // 2, (height - crop_height) // 2
    image = image.crop((left, top, left + crop_width, top + crop_height)).resize(OG_SIZE, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True, progressive=False)
    return buffer.getvalue()


def _finding(code: str, severity: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def readiness(
    truth: BusinessTruth,
    *,
    has_generated_icons: bool,
    third_party_services: tuple[str, ...],
    owner_review_claims: tuple[str, ...],
    unverified_claims: list[dict[str, str]],
) -> list[dict[str, str]]:
    """What the OWNER must still provide or confirm before a real launch —
    reported, never guessed. Artifact validity is the contracts' job."""
    out = [
        _finding(
            "legal_identity_missing",
            "launch_blocker",
            f"{field} is not in BusinessTruth; the legal pages state it as not provided. The owner must provide it "
            "(and have the legal texts reviewed) before launch.",
        )
        for field in legal_owner_input_required(truth)
    ]
    out.append(
        _finding(
            "legal_text_review",
            "owner_review",
            "Privacy, legal notice and cookie texts are platform template wording; they need owner/legal review. A "
            "page or banner existing is not legal compliance.",
        )
    )
    if truth.logo is None:
        out.append(
            _finding(
                "logo_not_provided", "info", "No owner-approved logo in BusinessTruth: no generated mark is shown."
            )
        )
        if has_generated_icons:
            out.append(
                _finding(
                    "favicon_from_generated_mark",
                    "owner_review",
                    "The favicon/app icons shipped with the export were generated by the builder; the owner must "
                    "approve or replace them.",
                )
            )
    contact = truth.contact
    if contact.phone or contact.email or contact.whatsapp is not None or contact.address is not None:
        out.append(
            _finding(
                "contact_without_design_slot",
                "owner_review",
                "BusinessTruth has contact data the export's design may not show; it is in structured data only. A "
                "visible element is a design decision.",
            )
        )
    else:
        out.append(
            _finding(
                "form_only_contact",
                "info",
                "No phone, email, WhatsApp or address in BusinessTruth: the form is the only contact channel.",
            )
        )
    out += [_finding("claim_needs_owner_confirmation", "owner_review", claim) for claim in owner_review_claims]
    out += [_finding("unverified_factual_claim", "launch_blocker", c["detail"]) for c in unverified_claims]
    out += [
        _finding(
            "third_party_font_service",
            "owner_review",
            f"{service}: a typeface is served by a third party (visitors' IPs reach it); disclosed on /cookies.",
        )
        for service in third_party_services
    ]
    return out
