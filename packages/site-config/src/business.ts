import type { SiteConfig } from "./site-config.ts";

/** A physical/mailing address, following schema.org's `PostalAddress` shape. */
export interface LocalBusinessAddress {
  streetAddress: string;
  addressLocality: string;
  addressRegion?: string;
  postalCode?: string;
  /** ISO 3166-1 alpha-2 country code, e.g. "ES". */
  addressCountry: string;
}

/** One opening-hours rule: a set of days sharing the same opening/closing time. */
export interface LocalBusinessOpeningHours {
  /** Full English day names, e.g. `["Monday", "Tuesday"]` — schema.org's expected `DayOfWeek` values. */
  dayOfWeek: string[];
  /** 24h "HH:MM", e.g. "09:00". */
  opens: string;
  /** 24h "HH:MM", e.g. "18:00". */
  closes: string;
}

/**
 * Structured business/contact data, kept separate from `BrandConfig` (which
 * is purely visual identity — name/logo/tagline) and from the free-text
 * `ContactDetailConfig[]` a `Contact` block renders. This is the
 * machine-readable version of the same facts, and it's what
 * `buildLocalBusinessJsonLd` reads to generate schema.org markup. Every
 * field is optional — a client without a public address, for instance,
 * simply omits it, and the generated JSON-LD omits it too rather than
 * emitting a placeholder.
 */
export interface LocalBusinessConfig {
  telephone?: string;
  email?: string;
  address?: LocalBusinessAddress;
  openingHours?: LocalBusinessOpeningHours[];
  /** e.g. "€€", "$$$" — schema.org's free-text `priceRange`. */
  priceRange?: string;
}

/** The JSON-LD object shape `buildLocalBusinessJsonLd` produces. */
export interface LocalBusinessJsonLd {
  "@context": "https://schema.org";
  "@type": "LocalBusiness";
  name: string;
  telephone?: string;
  email?: string;
  priceRange?: string;
  address?: {
    "@type": "PostalAddress";
    streetAddress: string;
    addressLocality: string;
    addressRegion?: string;
    postalCode?: string;
    addressCountry: string;
  };
  openingHoursSpecification?: Array<{
    "@type": "OpeningHoursSpecification";
    dayOfWeek: string[];
    opens: string;
    closes: string;
  }>;
}

/**
 * Builds a schema.org `LocalBusiness` JSON-LD object from the data a
 * `SiteConfig` already carries (`brand.name` plus the optional `business`
 * field), so a client doesn't hand-write structured data. Returns
 * `undefined` when `siteConfig.business` isn't set — no `business` data
 * means nothing to generate, not a broken/empty script tag. Fields left
 * unset within `business` are simply omitted from the result, rather than
 * emitted as `null`/empty placeholders schema.org validators would flag.
 */
export function buildLocalBusinessJsonLd(siteConfig: SiteConfig): LocalBusinessJsonLd | undefined {
  const { business, brand } = siteConfig;
  if (!business) return undefined;

  const jsonLd: LocalBusinessJsonLd = {
    "@context": "https://schema.org",
    "@type": "LocalBusiness",
    name: brand.name,
  };

  if (business.telephone) jsonLd.telephone = business.telephone;
  if (business.email) jsonLd.email = business.email;
  if (business.priceRange) jsonLd.priceRange = business.priceRange;

  if (business.address) {
    jsonLd.address = { "@type": "PostalAddress", ...business.address };
  }

  if (business.openingHours && business.openingHours.length > 0) {
    jsonLd.openingHoursSpecification = business.openingHours.map((rule) => ({
      "@type": "OpeningHoursSpecification",
      dayOfWeek: rule.dayOfWeek,
      opens: rule.opens,
      closes: rule.closes,
    }));
  }

  return jsonLd;
}
