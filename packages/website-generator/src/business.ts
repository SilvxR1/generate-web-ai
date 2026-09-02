import type { BusinessProfile } from "@generate-web-ai/business-config-types";
import type { LocalBusinessAddress, LocalBusinessConfig, LocalBusinessOpeningHours } from "@generate-web-ai/site-config";

// packages/site-config's LocalBusinessOpeningHours.dayOfWeek expects
// schema.org's full English day names; BusinessProfile.business_hours
// uses the lowercase Weekday enum (app.domain.enums.Weekday on the
// Python side). This is the one place that conversion happens.
const WEEKDAY_TO_SCHEMA_ORG: Record<string, string> = {
  monday: "Monday",
  tuesday: "Tuesday",
  wednesday: "Wednesday",
  thursday: "Thursday",
  friday: "Friday",
  saturday: "Saturday",
  sunday: "Sunday",
};

function buildAddress(profile: BusinessProfile): LocalBusinessAddress | undefined {
  const address = profile.contact?.address;
  if (!address) return undefined;

  return {
    streetAddress: address.street_address,
    addressLocality: address.locality,
    ...(address.region ? { addressRegion: address.region } : {}),
    ...(address.postal_code ? { postalCode: address.postal_code } : {}),
    addressCountry: address.country,
  };
}

function buildOpeningHours(profile: BusinessProfile): LocalBusinessOpeningHours[] | undefined {
  if (!profile.business_hours || profile.business_hours.length === 0) return undefined;

  return profile.business_hours.map((rule) => ({
    dayOfWeek: rule.days.map((day) => WEEKDAY_TO_SCHEMA_ORG[day] ?? day),
    opens: rule.opens,
    closes: rule.closes,
  }));
}

/** Only built from real BusinessProfile.contact/business_hours data —
 * `undefined` (SiteConfig.business is optional) when there's nothing
 * real to report, never a placeholder object. */
export function buildBusiness(profile: BusinessProfile): LocalBusinessConfig | undefined {
  const { contact } = profile;
  const address = buildAddress(profile);
  const openingHours = buildOpeningHours(profile);

  if (!contact?.phone && !contact?.email && !address && !openingHours) {
    return undefined;
  }

  return {
    ...(contact?.phone ? { telephone: contact.phone } : {}),
    ...(contact?.email ? { email: contact.email } : {}),
    ...(address ? { address } : {}),
    ...(openingHours ? { openingHours } : {}),
  };
}
