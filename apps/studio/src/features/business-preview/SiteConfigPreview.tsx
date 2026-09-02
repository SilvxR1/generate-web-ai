import type { BlockConfig, PageConfig, SiteConfig } from "@generate-web-ai/site-config";

/**
 * A minimal, purpose-built rendering of the exact SiteConfig
 * `generateSiteConfig()` produced — not a second general-purpose block
 * renderer. The real renderer (@generate-web-ai/renderer) is a set of
 * `.astro` components with a peer dependency on Astro; embedding it live
 * inside this Vite/React SPA isn't viable (different rendering model
 * entirely — Astro components compile at build time, not in a browser
 * React tree). This shows the same data — hero/services/CTA/contact/
 * branding — the way the real site would.
 */
export function SiteConfigPreview({ siteConfig }: { siteConfig: SiteConfig }) {
  const page = siteConfig.pages[0];
  const hero = findBlock(page, "hero");
  const services = findBlock(page, "services");
  const cta = findBlock(page, "cta");
  const contact = findBlock(page, "contact");

  return (
    <div className="site-preview">
      <div className="site-preview__brand">
        <div className="site-preview__palette">
          {(Object.entries(siteConfig.theme.colors) as Array<[string, string]>).map(([name, value]) => (
            <span key={name} className="site-preview__swatch" style={{ background: value }} title={`${name}: ${value}`} />
          ))}
        </div>
        <span className="site-preview__brand-name">{siteConfig.brand.name}</span>
        {siteConfig.brand.tagline && <span className="site-preview__tagline">{siteConfig.brand.tagline}</span>}
        <span className="site-preview__fonts">
          {siteConfig.theme.fonts.sans}
          {siteConfig.theme.fonts.display ? ` / ${siteConfig.theme.fonts.display}` : ""}
        </span>
      </div>

      {hero && (
        <section className="site-preview__hero">
          {hero.content.eyebrow && <p className="site-preview__eyebrow">{hero.content.eyebrow}</p>}
          <h2>{hero.content.heading}</h2>
          {hero.content.subheading && <p>{hero.content.subheading}</p>}
          <div className="site-preview__actions">
            {hero.content.primaryAction && <span className="site-preview__button site-preview__button--solid">{hero.content.primaryAction.label}</span>}
            {hero.content.secondaryAction && <span className="site-preview__button">{hero.content.secondaryAction.label}</span>}
          </div>
        </section>
      )}

      {services && (
        <section className="site-preview__section">
          {services.content.heading && <h3>{services.content.heading}</h3>}
          <ul className="site-preview__services">
            {services.content.items.map((item) => (
              <li key={item.title}>
                <strong>{item.title}</strong>
                <p>{item.description}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {cta && (
        <section className="site-preview__cta">
          <h3>{cta.content.heading}</h3>
          {cta.content.subheading && <p>{cta.content.subheading}</p>}
          <span className="site-preview__button site-preview__button--solid">{cta.content.primaryAction.label}</span>
        </section>
      )}

      {contact && (
        <section className="site-preview__section">
          {contact.content.heading && <h3>{contact.content.heading}</h3>}
          {contact.content.details && contact.content.details.length > 0 && (
            <ul className="site-preview__contact-details">
              {contact.content.details.map((detail) => (
                <li key={detail.label}>
                  {detail.label}: {detail.value}
                </li>
              ))}
            </ul>
          )}
          {contact.content.form && (
            <p className="field-hint">Lead form fields: {contact.content.form.fields.map((field) => field.label).join(", ")}</p>
          )}
        </section>
      )}

      {!hero && !services && !cta && !contact && (
        <p className="field-hint">This business's config doesn't have enough content yet for a website preview.</p>
      )}
    </div>
  );
}

function findBlock<T extends BlockConfig["type"]>(
  page: PageConfig | undefined,
  type: T,
): Extract<BlockConfig, { type: T }> | undefined {
  return page?.blocks.find((block): block is Extract<BlockConfig, { type: T }> => block.type === type);
}
