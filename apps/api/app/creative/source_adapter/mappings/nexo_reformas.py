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

import io
import json
from pathlib import Path

from PIL import Image

import app.creative.frontend_engine as frontend_engine
from app.creative.frontend_engine.legal_pages import legal_owner_input_required, legal_page_content
from app.creative.source_adapter.mapping import BusinessTruthGapError, ReadinessFinding, SiteContext, SourceMapping
from app.creative.source_adapter.records import (
    ContentBinding,
    JsonFieldPatch,
    JsonFieldSet,
    NewBinaryFile,
    NewFile,
    SourcePatch,
)
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
_SECTIONS = "src/components/nexo/sections.tsx"
_JOURNEY = "src/components/nexo/journey.tsx"

# The services the export presents, by BusinessTruth service id -> the
# literal Higgsfield wrote. Every one must exist in BusinessTruth
# (BusinessTruthGapError otherwise); the rendered name is the truth's.
SITE_SERVICES = {
    "reforma-integral": "Reforma integral",
    "cocina": "Cocina",
    "bano": "Baño",
    "pintura": "Pintura",
}
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
        'import { HONEYPOT_FIELD_NAME, TIMING_FIELD_NAME, submitLead } from "@/lib/platform-sdk";\n'
        'import { BUSINESS } from "@/platform/business";\n\n'
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
        "  // One id per submission attempt series: a retry after a failure reuses\n"
        "  // it, so the Lead API stores the lead at most once (H1.2).\n"
        '  const submissionId = useRef<string>("");\n'
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
        "    if (!submissionId.current) {\n"
        '      submissionId.current = globalThis.crypto?.randomUUID?.() ?? "";\n'
        "    }\n"
        "    // Every field the form asks travels to the Lead API: service and\n"
        "    // surface as labelled details, exactly as the visitor saw them (H1.2).\n"
        "    const sent = await submitLead(\n"
        "      {\n"
        "        email: payload.email,\n"
        "        message: payload.notes,\n"
        "        name: payload.name,\n"
        "        phone: payload.phone,\n"
        '        [HONEYPOT_FIELD_NAME]: String(raw.get(HONEYPOT_FIELD_NAME) ?? ""),\n'
        "        [TIMING_FIELD_NAME]: renderedAt.current,\n"
        "      },\n"
        "      scopeLabel,\n"
        "      {\n"
        "        details: [\n"
        '          { key: "service", label: "Tipo de reforma", value: scopeLabel },\n'
        '          { key: "surface_area", label: "Superficie aproximada", value: payload.area },\n'
        "        ],\n"
        "        submissionId: submissionId.current || undefined,\n"
        "      }\n"
        "    );\n"
        "    if (sent) {\n"
        '      submissionId.current = "";\n'
        '      setStatus("sent");\n'
        "      form.reset();\n"
        "    } else {\n"
        '      setStatus("error");\n'
        "    }\n",
        "submit through the SDK: scope -> subject, notes -> message, service + surface -> labelled details, "
        "one submission id per retry series; success only on a real 2xx, the existing error state otherwise",
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
    # --- BusinessTruth: services (names are facts; Higgsfield's copy stays) --
    SourcePatch(
        _SECTIONS,
        "const SERVICIOS = [\n",
        'import { BUSINESS } from "@/platform/business";\n\nconst SERVICIOS = [\n',
        "service names come from BusinessTruth (src/platform/business.ts)",
    ),
    *(
        SourcePatch(
            _SECTIONS,
            f'    name: "{literal}",\n',
            f'    name: BUSINESS.services["{service_id}"],\n',
            f"BusinessTruth service {service_id!r} (site literal {literal!r})",
        )
        for service_id, literal in SITE_SERVICES.items()
    ),
    *(
        SourcePatch(
            _LEAD_FORM,
            f'  {{ label: "{literal}", value: "{value}" }},\n',
            f'  {{ label: BUSINESS.services["{service_id}"], value: "{value}" }},\n',
            f"form option label = BusinessTruth service {service_id!r}",
        )
        for (service_id, literal), value in zip(
            SITE_SERVICES.items(), ("integral", "cocina", "bano", "pintura"), strict=True
        )
    ),
    # --- Brand policy: a logo only if the owner provided one -----------------
    SourcePatch(
        _JOURNEY,
        'import { scrollScrubScenes, scrollScrubTheme } from "@/scroll-scrub-scenes";\n',
        'import { BUSINESS } from "@/platform/business";\n'
        'import { scrollScrubScenes, scrollScrubTheme } from "@/scroll-scrub-scenes";\n',
        "brand mark from BusinessTruth",
    ),
    SourcePatch(
        _JOURNEY,
        "          <img\n"
        '            alt=""\n'
        '            aria-hidden="true"\n'
        '            className="nx-nav__mark"\n'
        "            height={22}\n"
        '            src="/assets/kit/nexo-mark.png"\n'
        "            width={22}\n"
        "          />\n",
        "          {/* GWA brand policy: only an owner-approved logo (BusinessTruth) is\n"
        "              shown here — the Higgsfield-generated mark is a placeholder. */}\n"
        "          {BUSINESS.logo ? (\n"
        "            <img\n"
        '              alt=""\n'
        '              aria-hidden="true"\n'
        '              className="nx-nav__mark"\n'
        "              height={22}\n"
        "              src={BUSINESS.logo.src}\n"
        "              width={22}\n"
        "            />\n"
        "          ) : null}\n",
        "the generated brand mark is not a client-approved logo (TruthContract brand policy)",
        visible="nav brand mark shown only for an owner-approved logo in BusinessTruth (none for Nexo: wordmark only)",
    ),
    # --- SEO: canonical, og:url and truth-only structured data ----------------
    SourcePatch(
        "src/routes/index.tsx",
        "  // The home page inherits the site's page metadata from the root route\n"
        "  // (title, favicon, og tags) so a shared link shows the owner's values.\n"
        "  component: Index,\n",
        "  // The home page inherits the site's page metadata from the root route\n"
        "  // (title, favicon, og tags) so a shared link shows the owner's values.\n"
        "  // GWA platform (H1.2): canonical URL, og:url and structured data built\n"
        "  // only from BusinessTruth (src/platform/business.ts).\n"
        "  head: () => ({\n"
        '    links: [{ rel: "canonical", href: `${BUSINESS.siteOrigin}/` }],\n'
        '    meta: [{ property: "og:url", content: `${BUSINESS.siteOrigin}/` }],\n'
        '    scripts: [{ type: "application/ld+json", children: SITE_JSONLD }],\n'
        "  }),\n"
        "  component: Index,\n",
        "canonical URL, og:url and JSON-LD from BusinessTruth",
    ),
    SourcePatch(
        "src/routes/index.tsx",
        'import { SiteFooter } from "@/components/nexo";\n',
        'import { SiteFooter } from "@/components/nexo";\n'
        'import { BUSINESS, SITE_JSONLD } from "@/platform/business";\n',
        "SEO data module",
    ),
    # --- Pre-existing Higgsfield layout defect (documented, design-preserving) -
    SourcePatch(
        "src/components/scroll-scrub/scroll-scrub.css",
        "@media (max-width: 860px) {\n  .scroll-scrub__poster,\n",
        "@media (max-width: 860px) {\n"
        "  /* GWA adapter (H1.2): the chapter scrim (.scroll-scrub__copy::before,\n"
        "     inset -2rem) reaches 12px past the viewport and made the whole page\n"
        "     scroll sideways. Clip horizontally only: nothing visible changes (the\n"
        "     clipped strip is outside the screen) and, unlike overflow:hidden,\n"
        "     clip creates no scroll container, so the sticky chapters still pin. */\n"
        "  .scroll-scrub {\n"
        "    overflow-x: clip;\n"
        "  }\n\n"
        "  .scroll-scrub__poster,\n",
        "pre-existing 12px horizontal overflow on mobile (Higgsfield), fixed without a visible change",
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
        Aviso legal
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
import { BUSINESS } from "@/platform/business";
import legal from "@/platform/legal-content.json";

/**
 * GWA platform legal page, composed only from the site's existing classes.
 * Content: BusinessTruth via app.creative.frontend_engine.legal_pages
 * (platform template wording — owner/legal review required; see readiness).
 */
export type LegalSlug = "privacy" | "terms" | "cookies";

export function legalHead(slug: LegalSlug) {
  const page = legal.pages[slug];
  return {
    meta: [{ title: page.metaTitle }, { name: "description", content: page.metaDescription }],
    links: [{ rel: "canonical", href: `${BUSINESS.siteOrigin}/${slug}` }],
  };
}

export function LegalPage({ slug }: { slug: LegalSlug }) {
  const page = legal.pages[slug];
  return (
    <div>
      <header className="nx-nav">
        <div className="nx-shell nx-nav__inner">
          <a className="nx-nav__brand" href="/">
            {BUSINESS.logo ? (
              <img
                alt=""
                aria-hidden="true"
                className="nx-nav__mark"
                height={22}
                src={BUSINESS.logo.src}
                width={22}
              />
            ) : null}
            {legal.businessName}
          </a>
          <a className="nx-cta-nav" href="/">
            <span>Volver al inicio</span>
          </a>
        </div>
      </header>
      <main className="nx-section">
        <article className="nx-shell max-w-[72ch]" lang={legal.lang}>
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

# Third-party services this site's source family loads, disclosed on the
# cookie page (trusted text; the CSP allows exactly these origins).
THIRD_PARTIES_ES = (
    "Fontshare (Indian Type Foundry) sirve la tipografía Cabinet Grotesk desde sus servidores "
    "(api.fontshare.com, cdn.fontshare.com); al cargar la página, tu navegador les envía tu dirección IP. "
    "No se usa para analítica.",
)

# Higgsfield-authored copy that states how the business works — kept (the
# editorial voice is Higgsfield's), but surfaced for the owner to confirm
# before launch. Never fabricated facts: none of these are counts, ratings,
# years, awards, certifications, prices or addresses.
OWNER_REVIEW_CLAIMS = (
    "Trabajamos vivienda vacía o habitada, con los oficios coordinados por nosotros y un único responsable del "
    "proyecto.",
    "Una persona responsable de la obra de principio a fin.",
    "Cada material que entra en obra queda descrito en el presupuesto, con su referencia y su superficie.",
    "Albañilería, fontanería, electricidad, carpintería, revestimientos y pintura. Un solo calendario para todos.",
    "Respondemos en horario laboral.",
    "Formulario de un minuto. Sin compromiso.",
)

_OG_SOURCE = "public/assets/world/nexo-06-poster.png"  # the export's own "delivered home" frame
_OG_SIZE = (1200, 630)


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
        raise BusinessTruthGapError("the Nexo mapping needs BusinessTruth location.city and a supported country")
    return {
        "identity.name": truth.identity.name,
        "location.city": city,
        "location.country_name": _COUNTRY_NAMES_ES[country],
    }


def _services(truth: BusinessTruth) -> dict[str, str]:
    """The export's services, by id, named from BusinessTruth. A service the
    site presents but the business never listed stops the adapter."""
    by_id = {service.id: service.name for service in truth.services}
    missing = [service_id for service_id in SITE_SERVICES if service_id not in by_id]
    if missing:
        raise BusinessTruthGapError(f"the site presents services missing from BusinessTruth: {missing}")
    return {service_id: by_id[service_id] for service_id in SITE_SERVICES}


def _json_ld(truth: BusinessTruth, site: SiteContext, services: dict[str, str]) -> dict:
    """schema.org data built ONLY from BusinessTruth — no rating, review,
    price, founding date or count is ever emitted; absent facts are absent."""
    data: dict = {
        "@context": "https://schema.org",
        "@type": "HomeAndConstructionBusiness",
        "name": truth.identity.name,
        "url": f"{site.origin}/",
        "areaServed": [
            {"@type": "City", "name": area} for area in [truth.location.city, *truth.location.service_area] if area
        ],
        "makesOffer": [
            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": name}} for name in services.values()
        ],
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


def _business_module(truth: BusinessTruth, site: SiteContext) -> str:
    services = _services(truth)
    logo = None if truth.logo is None else {"src": truth.logo.url, "alt": truth.logo.alt_text or ""}
    # `</` can never close the JSON-LD <script> the string is embedded in.
    json_ld = json.dumps(_json_ld(truth, site, services), ensure_ascii=False).replace("</", "<\\\\/")
    return (
        "/**\n"
        " * GWA platform (H1.2): business facts bound from BusinessTruth. Generated\n"
        " * on every build by app.creative.source_adapter — never edit by hand.\n"
        " */\n"
        "export const BUSINESS = {\n"
        f"  name: {json.dumps(truth.identity.name, ensure_ascii=False)},\n"
        f"  city: {json.dumps(truth.location.city, ensure_ascii=False)},\n"
        f"  services: {json.dumps(services, ensure_ascii=False)} as Record<string, string>,\n"
        f"  logo: {json.dumps(logo, ensure_ascii=False)} as null | {{ src: string; alt: string }},\n"
        f"  siteOrigin: {json.dumps(site.origin)},\n"
        "};\n\n"
        f"export const SITE_JSONLD = {json.dumps(json_ld, ensure_ascii=False)};\n"
    )


def derived_files(app: Path) -> list[NewBinaryFile]:
    """The owned Open Graph image: the export's own final-chapter frame,
    center-cropped to 1200x630 JPEG (deterministic: fixed crop, quality,
    no metadata). No text is drawn, so no font file is ever needed."""
    with Image.open(app / _OG_SOURCE) as source:
        image = source.convert("RGB")
    width, height = image.size
    target_ratio = _OG_SIZE[0] / _OG_SIZE[1]
    crop_width = min(width, round(height * target_ratio))
    crop_height = round(crop_width / target_ratio)
    left, top = (width - crop_width) // 2, (height - crop_height) // 2
    image = image.crop((left, top, left + crop_width, top + crop_height)).resize(_OG_SIZE, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True, progressive=False)
    return [
        NewBinaryFile(
            "public/og-image.jpg",
            buffer.getvalue(),
            f"owned Open Graph image derived from the export's {_OG_SOURCE} (no Higgsfield CDN)",
            visible="link previews show the site's own final-chapter frame",
        )
    ]


def json_sets(truth: BusinessTruth, site: SiteContext) -> list[JsonFieldSet]:
    return [
        JsonFieldSet(
            _META,
            "og_image_url",
            f"{site.origin}/og-image.jpg",
            "og:image = the owned, derived image, absolute on the site's canonical origin",
        )
    ]


def new_files(truth: BusinessTruth, site: SiteContext) -> list[NewFile | NewBinaryFile]:
    name = truth.identity.name
    pages = {
        slug: {
            "title": title,
            "metaTitle": f"{title} — {name}",
            "metaDescription": f"{title} de {name}" if site.locale == "es" else f"{title} for {name}",
            "paragraphs": paragraphs,
        }
        for slug, (title, paragraphs) in legal_page_content(
            truth, locale=site.locale, third_parties=THIRD_PARTIES_ES if site.locale == "es" else ()
        ).items()
    }
    legal_json = (
        json.dumps({"businessName": name, "lang": site.locale, "pages": pages}, ensure_ascii=False, indent=2) + "\n"
    )
    return [
        NewFile(
            "src/lib/platform-sdk.ts",
            _PLATFORM_SDK_TEMPLATE.read_text(encoding="utf-8"),
            "GWA Platform SDK, verbatim (the same file every generative site receives)",
        ),
        NewFile("src/platform/business.ts", _business_module(truth, site), "business facts from BusinessTruth"),
        NewFile("src/platform/legal-content.json", legal_json, "legal wording rendered from BusinessTruth"),
        NewFile("src/platform/consent-theme.ts", _CONSENT_THEME_TS, "consent banner theme = the site's own tokens"),
        NewFile(
            "src/components/nexo/legal-links.tsx",
            _LEGAL_LINKS_TSX,
            "footer/legal-page legal navigation",
            visible="footer legal links (Privacidad, Aviso legal, Cookies, Preferencias de cookies)",
        ),
        NewFile(
            "src/components/nexo/legal-page.tsx",
            _LEGAL_PAGE_TSX,
            "legal page layout from the site's existing classes (nx-nav, nx-shell, nx-display, nx-mono)",
            visible="new pages /privacy, /terms (Aviso legal), /cookies",
        ),
        NewFile("src/routes/privacy.tsx", _legal_route("privacy", "PrivacyPage"), "legal route /privacy"),
        NewFile("src/routes/terms.tsx", _legal_route("terms", "TermsPage"), "legal route /terms (Aviso legal)"),
        NewFile("src/routes/cookies.tsx", _legal_route("cookies", "CookiesPage"), "legal route /cookies"),
    ]


def readiness(truth: BusinessTruth) -> list[ReadinessFinding]:
    """What the OWNER must still provide or confirm before a real launch —
    reported, never guessed. Artifact validity is the contracts' job."""
    findings = [
        ReadinessFinding(
            "legal_identity_missing",
            "launch_blocker",
            f"{field} is not in BusinessTruth; the Spanish legal pages state «no facilitado». The owner must "
            "provide it (and have the legal texts reviewed) before launch.",
        )
        for field in legal_owner_input_required(truth)
    ]
    findings.append(
        ReadinessFinding(
            "legal_text_review",
            "owner_review",
            "Privacy, legal notice and cookie texts are platform template wording; they need owner/legal review. "
            "A page or banner existing is not legal compliance.",
        )
    )
    if truth.logo is None:
        findings.append(
            ReadinessFinding(
                "logo_not_provided",
                "info",
                "No owner-approved logo in BusinessTruth: the Higgsfield-generated brand mark is not shown "
                "(nav and legal pages use the wordmark only).",
            )
        )
        findings.append(
            ReadinessFinding(
                "favicon_from_generated_mark",
                "owner_review",
                "The favicon/app icons shipped with the export derive from the generated mark; the owner must "
                "approve or replace them.",
            )
        )
    contact = truth.contact
    if contact.phone or contact.email or contact.whatsapp is not None or contact.address is not None:
        findings.append(
            ReadinessFinding(
                "contact_without_design_slot",
                "owner_review",
                "BusinessTruth has contact data, but this Higgsfield design has no contact/WhatsApp element; it is "
                "only in structured data. Adding a visible element is a design decision (Higgsfield).",
            )
        )
    else:
        findings.append(
            ReadinessFinding(
                "form_only_contact",
                "info",
                "No phone, email, WhatsApp or address in BusinessTruth: the quote form is the only contact channel.",
            )
        )
    findings += [
        ReadinessFinding("claim_needs_owner_confirmation", "owner_review", claim) for claim in OWNER_REVIEW_CLAIMS
    ]
    findings.append(
        ReadinessFinding(
            "third_party_font_service",
            "owner_review",
            "Cabinet Grotesk is served by the Fontshare API (ITF FFL v2.0 does not clearly allow a SaaS platform "
            "to self-host it for client sites); visitors' IPs reach Fontshare. Disclosed on /cookies.",
        )
    )
    return findings


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
    locale="es",
    json_sets=json_sets,
    derived_files=derived_files,
    readiness=readiness,
)
