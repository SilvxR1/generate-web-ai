"""Nexo Reformas — the H1 source-specific mapping for ONE real Higgsfield
Supercomputer export (nexo-reformas-web.zip, SHA-256 below).

Everything here is fixed data applied by the reusable primitives in
app.creative.source_adapter.records: exact-once patches, typed content
bindings and platform-owned new files. Nothing is a free-form rewrite, and
nothing touches the site's composition — layout, CSS, the scroll-scrub film,
sections and copy stay Higgsfield's. What changes is platform behavior:

- lead transport: Higgsfield's D1 server function -> the GWA Platform SDK
  (public Lead API), same form DOM/validation/states;
- platform runtime: SDK globals (consent-gated analytics, window.gwaConsent)
  on every page; the consent banner is injected post-build by the platform;
- legal routes (/privacy, /terms, /cookies) rendered from BusinessTruth in
  the site's own classes, linked from the footer;
- asset ownership: Google-hosted fonts -> self-hosted OFL packages;
  Higgsfield-CDN Open Graph/marketplace images removed;
- business facts (name, city, country) bound from BusinessTruth;
- TanStack Start's documented prerender, so the build emits static HTML.
"""

import json
from pathlib import Path

import app.creative.frontend_engine as frontend_engine
from app.creative.frontend_engine.legal_pages import legal_page_content
from app.creative.source_adapter.mapping import SourceMapping
from app.creative.source_adapter.records import ContentBinding, JsonFieldPatch, NewFile, SourcePatch
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.business_profile import Location, ServiceOffering
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.business_truth import BusinessTruth
from app.domain.enums import BusinessVertical
from app.publishing.csp_policy import SourceFamily
from app.publishing.security_headers import CspExtensions

EXPORT_ZIP_SHA256 = "f3fbc3e76caf53f8df4ae6d6819be7afcd24190af396172cd0ca68de31e0ea8f"
# The same SDK file every generative workspace receives (workspace.py).
_PLATFORM_SDK_TEMPLATE = Path(frontend_engine.__file__).parent / "templates" / "platform_sdk.ts"

# What this source needs (validated against its family policy by
# app.publishing.csp_policy.validate_requested — fail closed): the scroll-scrub engine plays same-origin clips
# through blob: object URLs (source family: Higgsfield animated website);
# Cabinet Grotesk is served by Fontshare's own CSS API (site-specific; its
# licence text for self-hosting could not be verified — see the H1 report).
CSP_REQUIREMENTS = CspExtensions(
    media_blob=True,
    style_origins=("https://api.fontshare.com",),
    font_origins=("https://cdn.fontshare.com",),
)

# Exact versions (OFL-1.1 on the public registry, published > 24h ago —
# the export's own bunfig `minimumReleaseAge` guard applies).
ADDED_DEPENDENCIES = {"@fontsource/ibm-plex-mono": "5.3.0", "@fontsource/inter-tight": "5.3.0"}

# Higgsfield's D1 lead backend (and its `cloudflare:workers` binding access):
# replaced by the GWA public Lead API; a static artifact has no server.
REMOVED_BACKEND = ("src/lib/api/leads.functions.ts", "src/lib/api/example.functions.ts", "src/lib/bindings.server.ts")

_COUNTRY_NAMES_ES = {"ES": "España"}

_LEAD_FORM = "src/components/nexo/lead-form.tsx"
_ROOT = "src/routes/__root.tsx"
_FOOTER = "src/components/nexo/index.tsx"
_META = "src/app-meta.json"

PATCHES: tuple[SourcePatch, ...] = (
    # --- Lead form: transport only -------------------------------------------
    SourcePatch(
        _LEAD_FORM,
        'import { useState } from "react";\n\n'
        'import { submitLead, type LeadInput } from "@/lib/api/leads.functions";\n',
        'import { useEffect, useRef, useState } from "react";\n\n'
        "// GWA platform adapter: the lead transport is the GWA Platform SDK (public Lead API).\n"
        'import { HONEYPOT_FIELD_NAME, TIMING_FIELD_NAME, submitLead } from "@/lib/platform-sdk";\n\n'
        "type LeadInput = {\n"
        "  area: string;\n"
        "  email: string;\n"
        "  name: string;\n"
        "  notes: string;\n"
        "  phone: string;\n"
        '  scope: "integral" | "cocina" | "bano" | "pintura" | "otro";\n'
        "};\n",
        "lead transport: Higgsfield D1 server function -> GWA Platform SDK submitLead",
    ),
    SourcePatch(
        _LEAD_FORM,
        '  const [reference, setReference] = useState<string>("");\n',
        "  // When the form was rendered in the visitor's browser (the public Lead\n"
        "  // API's spam timing check) — never the prerender time.\n"
        '  const renderedAt = useRef<string>("");\n'
        "  useEffect(() => {\n"
        "    renderedAt.current = new Date().toISOString();\n"
        "  }, []);\n",
        "the GWA Lead API never returns a lead id; keep the spam-timing field instead",
    ),
    SourcePatch(
        _LEAD_FORM,
        '    setStatus("sending");\n'
        "    try {\n"
        "      const result = await submitLead({ data: payload });\n"
        "      setReference(result.id.slice(0, 8).toUpperCase());\n"
        '      setStatus("sent");\n'
        "      form.reset();\n"
        "    } catch {\n"
        '      setStatus("error");\n'
        "    }\n",
        '    setStatus("sending");\n'
        '    const scopeLabel = SCOPES.find((scope) => scope.value === payload.scope)?.label ?? "";\n'
        "    // The public Lead API has no structured field for the surface: it\n"
        "    // travels as a labelled line of the message, never dropped.\n"
        '    const message = [payload.notes, payload.area ? `Superficie aproximada: ${payload.area}` : ""]\n'
        "      .filter(Boolean)\n"
        '      .join("\\n\\n");\n'
        "    const sent = await submitLead(\n"
        "      {\n"
        "        email: payload.email,\n"
        "        message,\n"
        "        name: payload.name,\n"
        "        phone: payload.phone,\n"
        '        [HONEYPOT_FIELD_NAME]: String(raw.get(HONEYPOT_FIELD_NAME) ?? ""),\n'
        "        [TIMING_FIELD_NAME]: renderedAt.current,\n"
        "      },\n"
        "      scopeLabel\n"
        "    );\n"
        "    if (sent) {\n"
        '      setStatus("sent");\n'
        "      form.reset();\n"
        "    } else {\n"
        '      setStatus("error");\n'
        "    }\n",
        "submit through the SDK: scope -> subject, notes (+ labelled surface) -> message; "
        "success only on a real 2xx, the existing error state otherwise",
    ),
    SourcePatch(
        _LEAD_FORM,
        '        <p className="nx-sent__ref">Solicitud recibida / {reference}</p>\n',
        '        <p className="nx-sent__ref">Solicitud recibida</p>\n',
        "no submission reference exists: the GWA Lead API deliberately never returns a lead id",
        visible='success state label "Solicitud recibida / <ref>" -> "Solicitud recibida" (no fabricated id)',
    ),
    SourcePatch(
        _LEAD_FORM,
        '    <form className="nx-form" noValidate onSubmit={handleSubmit}>\n',
        '    <form className="nx-form" data-gwa-lead-form="" noValidate onSubmit={handleSubmit}>\n',
        "PlatformContract lead-form hook (data attribute only)",
    ),
    SourcePatch(
        _LEAD_FORM,
        '      <div className="flex flex-wrap items-center gap-6">\n        <button className="nx-cta-submit"',
        "      {/* GWA platform: spam honeypot — visually hidden, never filled by a person. */}\n"
        '      <div aria-hidden="true" className="sr-only">\n'
        "        <label htmlFor={HONEYPOT_FIELD_NAME}>No rellenar</label>\n"
        '        <input autoComplete="off" id={HONEYPOT_FIELD_NAME} name={HONEYPOT_FIELD_NAME} tabIndex={-1} '
        'type="text" />\n'
        "      </div>\n\n"
        '      <div className="flex flex-wrap items-center gap-6">\n        <button className="nx-cta-submit"',
        "public Lead API honeypot field (visually hidden, aria-hidden, not focusable)",
    ),
    # --- Root: platform runtime, fonts, consent theming ----------------------
    SourcePatch(
        _ROOT,
        'import appCss from "../styles.css?url";\n',
        'import appCss from "../styles.css?url";\n'
        "// GWA adapter: self-hosted OFL fonts (were loaded from fonts.googleapis.com).\n"
        'import plexMono400 from "@fontsource/ibm-plex-mono/400.css?url";\n'
        'import plexMono500 from "@fontsource/ibm-plex-mono/500.css?url";\n'
        'import interTight400 from "@fontsource/inter-tight/400.css?url";\n'
        'import interTight500 from "@fontsource/inter-tight/500.css?url";\n'
        'import interTight600 from "@fontsource/inter-tight/600.css?url";\n'
        "// GWA adapter: platform runtime (consent-gated analytics, window.gwaConsent).\n"
        'import "@/lib/platform-sdk";\n'
        'import { GWA_CONSENT_THEME } from "@/platform/consent-theme";\n',
        "load the GWA Platform SDK on every page; self-hosted font stylesheets",
    ),
    SourcePatch(
        _ROOT,
        '      { rel: "preconnect", href: "https://fonts.googleapis.com" },\n'
        "      {\n"
        '        crossOrigin: "anonymous" as const,\n'
        '        href: "https://fonts.gstatic.com",\n'
        '        rel: "preconnect",\n'
        "      },\n"
        "      {\n"
        '        rel: "stylesheet",\n'
        '        href: "https://api.fontshare.com/v2/css?f%5B%5D=cabinet-grotesk@500,700,800&display=swap",\n'
        "      },\n"
        "      {\n"
        '        rel: "stylesheet",\n'
        '        href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Inter+Tight:'
        'wght@400;500;600&display=swap",\n'
        "      },\n"
        '      { rel: "stylesheet", href: appCss },\n',
        "      {\n"
        '        rel: "stylesheet",\n'
        '        href: "https://api.fontshare.com/v2/css?f%5B%5D=cabinet-grotesk@500,700,800&display=swap",\n'
        "      },\n"
        '      { rel: "stylesheet", href: plexMono400 },\n'
        '      { rel: "stylesheet", href: plexMono500 },\n'
        '      { rel: "stylesheet", href: interTight400 },\n'
        '      { rel: "stylesheet", href: interTight500 },\n'
        '      { rel: "stylesheet", href: interTight600 },\n'
        '      { rel: "stylesheet", href: appCss },\n',
        "Inter Tight / IBM Plex Mono: same families and weights, self-hosted; Cabinet Grotesk unchanged (Fontshare)",
    ),
    SourcePatch(
        _ROOT,
        '<html lang="es" data-theme="default-dark" style={{ colorScheme: "dark" }}>',
        '<html lang="es" data-theme="default-dark" style={{ colorScheme: "dark", ...GWA_CONSENT_THEME }}>',
        "theme the platform consent banner through its documented --gwa-consent-* variables only",
    ),
    # --- Footer: legal links + cookie preferences ----------------------------
    SourcePatch(
        _FOOTER,
        'import { LeadForm } from "./lead-form";\n',
        'import { LeadForm } from "./lead-form";\nimport { LegalLinks } from "./legal-links";\n',
        "footer legal links component",
    ),
    SourcePatch(
        _FOOTER,
        '          <p className="nx-mono">Toda la información de esta web es descriptiva</p>\n',
        "          <LegalLinks />\n"
        '          <p className="nx-mono">Toda la información de esta web es descriptiva</p>\n',
        "PlatformContract: the entry page links every legal page; cookie preferences reopen the consent banner",
        visible="footer bottom bar gains legal links (Privacidad, Términos, Cookies, Preferencias de cookies) "
        "in the site's existing mono label style",
    ),
    # --- Static build: the documented TanStack Start prerender ---------------
    SourcePatch(
        "vite.config.ts",
        '      tanstackStart({\n        server: { entry: "server" },\n      }),\n',
        "      tanstackStart({\n"
        '        server: { entry: "server" },\n'
        "        // GWA adapter: prerender the public pages to static HTML (TanStack\n"
        "        // Start's documented prerender) — the artifact needs no server.\n"
        "        prerender: { enabled: true, crawlLinks: false, autoSubfolderIndex: true, failOnError: true },\n"
        '        pages: [{ path: "/" }, { path: "/privacy" }, { path: "/terms" }, { path: "/cookies" }],\n'
        "      }),\n",
        "static artifact: prerender /, /privacy, /terms, /cookies into dist/client",
    ),
    SourcePatch(
        "vite.config.ts",
        "    server: {\n      watch: { usePolling: true, interval: 150 },\n    },\n",
        "    server: {\n      watch: { usePolling: true, interval: 150 },\n    },\n"
        "    // GWA adapter: the prerender preview server binds an IP literal — the\n"
        "    // R4 build sandbox has no /etc/hosts and no name resolution at all.\n"
        '    preview: { host: "127.0.0.1" },\n',
        "prerender inside the R4 sandbox: no hostname resolution needed",
    ),
)

# Asset ownership: no Higgsfield-hosted metadata images. Matched by the CDN
# host only, so no builder account path is stored here.
_HIGGSFIELD_CDN = "https://d2ol7oe51mr4n9.cloudfront.net/"
JSON_FIELDS: tuple[JsonFieldPatch, ...] = (
    JsonFieldPatch(
        _META,
        "og_image_url",
        _HIGGSFIELD_CDN,
        None,
        "Open Graph image hosted on Higgsfield's CDN removed (not bundled; to be chosen and ingested by GWA)",
        visible="link previews (social shares) show no image until GWA sets an owned og:image",
    ),
    JsonFieldPatch(
        _META,
        "marketplace_cover_url",
        _HIGGSFIELD_CDN,
        None,
        "Higgsfield marketplace cover (read only by the Higgsfield platform, never rendered) removed",
    ),
)

BINDINGS: tuple[ContentBinding, ...] = (
    ContentBinding(
        "src/components/nexo/journey.tsx", "\n          Nexo Reformas\n        </a>", "Nexo Reformas", "identity.name"
    ),
    ContentBinding(_FOOTER, '<p className="nx-display text-2xl">Nexo Reformas</p>', "Nexo Reformas", "identity.name"),
    ContentBinding(_FOOTER, "Reformas de vivienda en Valencia: proyectos", "Valencia", "location.city"),
    ContentBinding(_FOOTER, '<p className="nx-mono mt-6">Valencia, ', "Valencia", "location.city"),
    ContentBinding(_FOOTER, ", España</p>", "España", "location.country_name"),
    ContentBinding(_FOOTER, '<p className="nx-mono">Nexo Reformas</p>', "Nexo Reformas", "identity.name"),
    ContentBinding(_ROOT, 'const DEFAULT_TITLE = "Nexo Reformas |', "Nexo Reformas", "identity.name"),
    ContentBinding(_ROOT, 'Reformas de vivienda en Valencia";', "Valencia", "location.city"),
    ContentBinding(_ROOT, "pintura en Valencia. Presupuesto", "Valencia", "location.city"),
    ContentBinding(_ROOT, '{ name: "author", content: "Nexo Reformas" }', "Nexo Reformas", "identity.name"),
    ContentBinding(_ROOT, '{ property: "og:site_name", content: "Nexo Reformas" }', "Nexo Reformas", "identity.name"),
    ContentBinding(_META, '"og_title": "Nexo Reformas |', "Nexo Reformas", "identity.name"),
    ContentBinding(_META, 'Reformas de vivienda en Valencia",', "Valencia", "location.city"),
    ContentBinding(_META, "pintura en Valencia. Presupuesto", "Valencia", "location.city"),
)

# Hardcoded business content NOT bound (creative copy authored by Higgsfield):
# a Studio edit to any of these does not reach the site without a source edit.
UNBOUND_CONTENT = (
    "services (names, scopes, descriptions) — SERVICIOS in src/components/nexo/sections.tsx",
    "form service options — SCOPES in src/components/nexo/lead-form.tsx",
    "process, materials and quote copy — PROCESO/MATERIALES/PARTIDAS in sections.tsx",
    "journey chapter copy — src/scroll-scrub-scenes.ts",
    "tagline/description copy in the footer and SEO description",
)

_LEGAL_LINKS_TSX = """/**
 * GWA platform: legal routes and cookie preferences, in the site's own mono
 * label style. `data-open-consent-preferences` reopens the platform banner.
 */
export function LegalLinks() {
  return (
    <nav aria-label="Legal" className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <a className="nx-mono" href="/privacy">
        Privacidad
      </a>
      <a className="nx-mono" href="/terms">
        Términos
      </a>
      <a className="nx-mono" href="/cookies">
        Cookies
      </a>
      <button className="nx-mono" data-open-consent-preferences="" type="button">
        Preferencias de cookies
      </button>
    </nav>
  );
}
"""

_LEGAL_PAGE_TSX = """import { LegalLinks } from "@/components/nexo/legal-links";
import legal from "@/platform/legal-content.json";

/**
 * GWA platform legal page, composed only from the site's existing classes.
 * Content: BusinessTruth via app.creative.frontend_engine.legal_pages
 * (platform wording, English — see the H1 report).
 */
export type LegalSlug = "privacy" | "terms" | "cookies";

export function legalHead(slug: LegalSlug) {
  const page = legal.pages[slug];
  return {
    meta: [{ title: page.metaTitle }, { name: "description", content: page.metaDescription }],
  };
}

export function LegalPage({ slug }: { slug: LegalSlug }) {
  const page = legal.pages[slug];
  return (
    <div>
      <header className="nx-nav">
        <div className="nx-shell nx-nav__inner">
          <a className="nx-nav__brand" href="/">
            <img
              alt=""
              aria-hidden="true"
              className="nx-nav__mark"
              height={22}
              src="/assets/kit/nexo-mark.png"
              width={22}
            />
            {legal.businessName}
          </a>
          <a className="nx-cta-nav" href="/">
            <span>Volver al inicio</span>
          </a>
        </div>
      </header>
      <main className="nx-section">
        <article className="nx-shell max-w-[72ch]" lang="en">
          <p className="nx-mono">Legal</p>
          <h1 className="nx-display mt-5 text-4xl md:text-5xl">{page.title}</h1>
          {page.paragraphs.map((paragraph) => (
            <p className="mt-6 text-base leading-relaxed text-ash" key={paragraph}>
              {paragraph}
            </p>
          ))}
        </article>
      </main>
      <footer className="border-t border-hair">
        <div className="nx-shell flex flex-wrap items-center justify-between gap-3 py-5">
          <p className="nx-mono">{legal.businessName}</p>
          <LegalLinks />
        </div>
      </footer>
    </div>
  );
}
"""

_CONSENT_THEME_TS = """import type { CSSProperties } from "react";

/**
 * GWA platform consent banner, themed ONLY through its documented
 * --gwa-consent-* custom properties, pointed at the site's own tokens
 * (src/styles.css :root). Set on <html> so no stylesheet targets the banner.
 */
export const GWA_CONSENT_THEME = {
  "--gwa-consent-bg": "var(--nx-surface)",
  "--gwa-consent-fg": "var(--nx-bone)",
  "--gwa-consent-accent": "var(--nx-verdigris)",
  "--gwa-consent-accent-fg": "var(--nx-ground)",
  "--gwa-consent-radius": "0",
} as CSSProperties;
"""


def _legal_route(slug: str, component: str) -> str:
    return f"""import {{ createFileRoute }} from "@tanstack/react-router";

import {{ LegalPage, legalHead }} from "@/components/nexo/legal-page";

// GWA platform legal route (content from BusinessTruth).
export const Route = createFileRoute("/{slug}")({{
  head: () => legalHead("{slug}"),
  component: {component},
}});

function {component}() {{
  return <LegalPage slug="{slug}" />;
}}
"""


def truth_values(truth: BusinessTruth) -> dict[str, str]:
    city, country = truth.location.city, truth.location.country
    if not city or country not in _COUNTRY_NAMES_ES:
        raise ValueError("the Nexo mapping needs BusinessTruth location.city and a supported location.country")
    return {
        "identity.name": truth.identity.name,
        "location.city": city,
        "location.country_name": _COUNTRY_NAMES_ES[country],
    }


def new_files(truth: BusinessTruth) -> list[NewFile]:
    name = truth.identity.name
    pages = {
        slug: {
            "title": title,
            "metaTitle": f"{title} — {name}",
            "metaDescription": f"{title} for {name}",
            "paragraphs": paragraphs,
        }
        for slug, (title, paragraphs) in legal_page_content(truth).items()
    }
    legal_json = json.dumps({"businessName": name, "pages": pages}, ensure_ascii=False, indent=2) + "\n"
    return [
        NewFile(
            "src/lib/platform-sdk.ts",
            _PLATFORM_SDK_TEMPLATE.read_text(encoding="utf-8"),
            "GWA Platform SDK, verbatim (the same file every generative site receives)",
        ),
        NewFile("src/platform/legal-content.json", legal_json, "legal wording rendered from BusinessTruth"),
        NewFile("src/platform/consent-theme.ts", _CONSENT_THEME_TS, "consent banner theme = the site's own tokens"),
        NewFile("src/components/nexo/legal-links.tsx", _LEGAL_LINKS_TSX, "footer/legal-page legal navigation"),
        NewFile(
            "src/components/nexo/legal-page.tsx",
            _LEGAL_PAGE_TSX,
            "legal page layout from the site's existing classes (nx-nav, nx-shell, nx-display, nx-mono)",
            visible="new pages /privacy, /terms, /cookies",
        ),
        NewFile("src/routes/privacy.tsx", _legal_route("privacy", "PrivacyPage"), "legal route /privacy"),
        NewFile("src/routes/terms.tsx", _legal_route("terms", "TermsPage"), "legal route /terms"),
        NewFile("src/routes/cookies.tsx", _legal_route("cookies", "CookiesPage"), "legal route /cookies"),
    ]


def h1_fixture_business_config() -> BusinessConfig:
    """The FICTIONAL H1 business, limited to the owner brief: name, city,
    the four services, lead capture by form (name + phone). No contact
    data, legal identifiers, logo, reviews, ratings, counts or claims."""
    services = [
        ("reforma-integral", "Reforma integral", "Reforma completa de vivienda."),
        ("cocina", "Cocina", "Reforma de cocinas."),
        ("bano", "Baño", "Reforma de baños."),
        ("pintura", "Pintura", "Pintura de vivienda."),
    ]
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Nexo Reformas",
            slug="nexo-reformas",
            industry=BusinessVertical.HOME_RENOVATION,
            location=Location(city="Valencia", country="ES"),
            services=[ServiceOffering(id=i, name=n, description=d) for i, n, d in services],
        ),
        lead_management=LeadManagementConfig(enabled=True, required_fields=["name", "phone"]),
        automation=AutomationConfig(lead_capture=True),
    )


MAPPING = SourceMapping(
    name="higgsfield-supercomputer/nexo-reformas",
    export_zip_sha256=EXPORT_ZIP_SHA256,
    source_family=SourceFamily.HIGGSFIELD_TANSTACK,
    csp_requirements=CSP_REQUIREMENTS,
    added_dependencies=ADDED_DEPENDENCIES,
    removed_files=REMOVED_BACKEND,
    patches=PATCHES,
    bindings=BINDINGS,
    new_files=new_files,
    truth_values=truth_values,
    unbound_content=UNBOUND_CONTENT,
    json_fields=JSON_FIELDS,
)
