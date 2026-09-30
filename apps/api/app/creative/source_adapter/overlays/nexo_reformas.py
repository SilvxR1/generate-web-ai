"""Reviewed overlay for ONE Higgsfield export: nexo-reformas-web.zip.

Data, not code: it applies only to the snapshot with the SHA-256 below and
records the human decisions accepted in H1.2 (PR #69) that the
higgsfield-tanstack-static adapter cannot infer from the source:

- approved edits of the original export, each tied to the finding it
  resolves (the fabricated submission reference; a pre-existing 12px
  mobile overflow, fixed without a visible change);
- the consent banner theme (the site's own tokens);
- where the legal links sit in this design and which classes they use,
  and a legal page composed from the site's own classes;
- the frame the owned share image is cropped from;
- qualitative claims the owner must confirm before launch.

Everything else (lead transport, BusinessTruth bindings, SEO, fonts, the
brand policy, prerendering) is derived by the family adapter.
"""

from app.creative.source_adapter.adapters.base import ExportOverlay, LegalPresentation, OverlayPatch
from app.creative.source_adapter.platform_files import LEGAL_HEAD_TS, LEGAL_PAGE_IMPORTS

SNAPSHOT_ZIP_SHA256 = "f3fbc3e76caf53f8df4ae6d6819be7afcd24190af396172cd0ca68de31e0ea8f"
_LEAD_FORM = "src/components/nexo/lead-form.tsx"
_REFERENCE_FINDING = f"form_displays_server_identifier:{_LEAD_FORM}#0"

_LEGAL_PAGE_TSX = (
    LEGAL_PAGE_IMPORTS
    + """
/**
 * GWA platform legal page, composed only from the site's existing classes.
 * Content: BusinessTruth (platform template wording — owner/legal review).
 */
"""
    + LEGAL_HEAD_TS
    + """
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
)

OVERLAY = ExportOverlay(
    name="nexo-reformas",
    snapshot_zip_sha256=SNAPSHOT_ZIP_SHA256,
    reviewed="GWA operator review of the H1.2 acceptance (PR #69, 2026-09-30): design decisions and fixes accepted",
    resolutions={
        _REFERENCE_FINDING: "the success state no longer shows the server-generated reference (the GWA Lead API "
        "returns none; nothing is fabricated)",
    },
    patches=(
        OverlayPatch(
            _LEAD_FORM,
            "      setReference(result.id.slice(0, 8).toUpperCase());\n",
            "",
            "no submission reference exists: the GWA Lead API deliberately never returns a lead id",
            category="lead-transport",
            resolves=(_REFERENCE_FINDING,),
        ),
        OverlayPatch(
            _LEAD_FORM,
            '        <p className="nx-sent__ref">Solicitud recibida / {reference}</p>\n',
            '        <p className="nx-sent__ref">Solicitud recibida</p>\n',
            "success label without a fabricated id",
            category="lead-transport",
            visible='success state label "Solicitud recibida / <ref>" -> "Solicitud recibida"',
            resolves=(_REFERENCE_FINDING,),
        ),
        OverlayPatch(
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
    ),
    consent_theme={
        "--gwa-consent-bg": "var(--nx-surface)",
        "--gwa-consent-fg": "var(--nx-bone)",
        "--gwa-consent-accent": "var(--nx-verdigris)",
        "--gwa-consent-accent-fg": "var(--nx-ground)",
        "--gwa-consent-radius": "0",
    },
    legal=LegalPresentation(
        nav_class="flex flex-wrap items-center gap-x-6 gap-y-2",
        link_class="nx-mono",
        links_anchor=(
            "src/components/nexo/index.tsx",
            '          <p className="nx-mono">Toda la información de esta web es descriptiva</p>\n',
        ),
        page_tsx=_LEGAL_PAGE_TSX,
    ),
    og_image_source="public/assets/world/nexo-06-poster.png",
    owner_review_claims=(
        "Trabajamos vivienda vacía o habitada, con los oficios coordinados por nosotros y un único responsable del "
        "proyecto.",
        "Una persona responsable de la obra de principio a fin.",
        "Cada material que entra en obra queda descrito en el presupuesto, con su referencia y su superficie.",
        "Albañilería, fontanería, electricidad, carpintería, revestimientos y pintura. Un solo calendario para todos.",
        "Respondemos en horario laboral.",
        "Formulario de un minuto. Sin compromiso.",
    ),
)
