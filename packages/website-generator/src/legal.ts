/**
 * BusinessConfig.legal_profile (+ business_profile) -> the three legal
 * pages every generated site gets: Privacy Policy, Terms of Service,
 * Cookie Policy. Same hard rule as the rest of this module (see
 * generateSiteConfig.ts's docstring): every fact here either comes
 * directly from BusinessConfig or is generic template copy — a missing
 * LegalProfile field renders as an explicit "Not provided" line, never
 * a fabricated value, and every page carries a visible disclaimer that
 * this is not legal advice (P0's "Do NOT claim guaranteed compliance,
 * lawyer-reviewed status" constraint) — see LegalTextBlockContent's own
 * docstring in packages/site-config for why `disclaimer` is a required
 * field rather than something a caller could omit.
 *
 * Deliberately produces the same three pages every time, unconditional
 * on how complete LegalProfile is: a business with nothing filled in
 * yet still gets pages that plainly say so, which is the incompleteness
 * signal itself doing its job (Studio's own legal-profile form is where
 * a human fills the gaps in) rather than this app silently omitting a
 * legal page a real site should have.
 */
import type { BusinessProfile, LegalProfile } from "@generate-web-ai/business-config-types";
import type { PageConfig, SiteLocale } from "@generate-web-ai/site-config";
import type { SpanishLegalOptions } from "./legal-es.ts";
import { buildSpanishLegalPages } from "./legal-es.ts";

const NOT_PROVIDED = "Not provided.";

const DISCLAIMER =
  "This page was generated automatically from the information provided in this business's legal profile, " +
  "plus general template text. It is not legal advice, has not been reviewed by a lawyer, and does not by " +
  "itself guarantee compliance with any law. Consult a legal professional to confirm it meets your obligations.";

function entityName(profile: BusinessProfile, legal: LegalProfile | undefined): string {
  return legal?.legal_name?.trim() || profile.name;
}

function formatAddress(legal: LegalProfile | undefined): string {
  const address = legal?.address;
  if (!address) return NOT_PROVIDED;
  return [address.street_address, address.locality, address.region, address.postal_code, address.country]
    .filter((part): part is string => Boolean(part && part.trim()))
    .join(", ");
}

function privacyContactEmail(profile: BusinessProfile, legal: LegalProfile | undefined): string {
  return legal?.privacy_contact_email || profile.contact?.email || NOT_PROVIDED;
}

function buildPrivacyPolicyPage(
  profile: BusinessProfile,
  legal: LegalProfile | undefined,
  hasContactForm: boolean,
): PageConfig {
  const name = entityName(profile, legal);
  const processors =
    legal?.data_processors && legal.data_processors.length > 0
      ? legal.data_processors.join(", ")
      : "No third-party data processors have been listed for this business.";

  return {
    path: "/privacy",
    blocks: [
      {
        type: "legal_text",
        content: {
          heading: "Privacy Policy",
          disclaimer: DISCLAIMER,
          sections: [
            {
              heading: "Who we are",
              body:
                `${name} operates this website.\n\n` +
                `Registered address: ${formatAddress(legal)}\n\n` +
                `Registration number: ${legal?.registration_number || NOT_PROVIDED}\n\n` +
                `Tax ID: ${legal?.tax_id || NOT_PROVIDED}\n\n` +
                `Contact for privacy questions: ${privacyContactEmail(profile, legal)}`,
            },
            {
              heading: "Information we collect",
              body: hasContactForm
                ? "If you submit this site's contact form, we collect the information you enter " +
                  "(such as your name, email address, phone number, and message) in order to respond to your " +
                  "inquiry. We do not collect any other personal information through this site."
                : "This site does not currently include a contact form or any other way for you to submit " +
                  "personal information to us.",
            },
            {
              heading: "Cookies",
              body:
                "This site's use of browser storage is described in its Cookie Policy. Its optional " +
                "analytics only runs after you accept it in the privacy notice.",
            },
            {
              heading: "Third parties we work with",
              body: processors,
            },
            {
              heading: "Your rights",
              body:
                "Depending on where you are located, applicable law may give you rights to access, correct, " +
                "or delete personal data we hold about you, or to object to how it's used. To exercise any of " +
                `these rights, contact us at ${privacyContactEmail(profile, legal)}.`,
            },
            {
              heading: "Changes to this policy",
              body: "We may update this policy from time to time. Continued use of this site after a change means you accept the updated policy.",
            },
          ],
        },
      },
    ],
  };
}

function buildTermsPage(profile: BusinessProfile, legal: LegalProfile | undefined): PageConfig {
  const name = entityName(profile, legal);

  return {
    path: "/terms",
    blocks: [
      {
        type: "legal_text",
        content: {
          heading: "Terms of Service",
          disclaimer: DISCLAIMER,
          sections: [
            {
              heading: "Acceptance of these terms",
              body: `By using this website, you agree to these terms. This website is operated by ${name}.`,
            },
            {
              heading: "Use of this website",
              body:
                "You agree to use this website only for lawful purposes and in a way that doesn't infringe " +
                "the rights of, or restrict or inhibit the use and enjoyment of this site by, anyone else.",
            },
            {
              heading: "No warranty",
              body:
                "This website and its content are provided as-is, without warranties of any kind, to the " +
                "fullest extent permitted by applicable law.",
            },
            {
              heading: "Contact",
              body: `Questions about these terms can be sent to ${privacyContactEmail(profile, legal)}.`,
            },
          ],
        },
      },
    ],
  };
}

function buildCookiePolicyPage(profile: BusinessProfile, legal: LegalProfile | undefined): PageConfig {
  const name = entityName(profile, legal);

  return {
    path: "/cookies",
    blocks: [
      {
        type: "legal_text",
        content: {
          heading: "Cookie Policy",
          disclaimer: DISCLAIMER,
          sections: [
            {
              heading: "How this site uses cookies",
              body:
                `${name}'s website code sets no cookies. It keeps your choice on the privacy notice in your ` +
                "browser's local storage so you are not asked again. If you accept the Analytics category, the " +
                "site sends its own server usage events without personal identifiers (for example, page visits " +
                "or clicks on contact links); if you don't, none are sent. Consent is never assumed or " +
                "pre-selected.",
            },
            {
              heading: "Managing your preferences",
              body:
                "You can change your cookie choices at any time using the \"Manage cookie preferences\" link " +
                "in this site's footer.",
            },
          ],
        },
      },
    ],
  };
}

/** C2.1: `locale` "es" switches to the Spanish client templates in
 * legal-es.ts (Aviso Legal / Privacidad / Cookies); omitted, the English
 * pages below are produced exactly as before. */
export function buildLegalPages(
  profile: BusinessProfile,
  legal: LegalProfile | undefined,
  hasContactForm: boolean,
  locale: SiteLocale = "en",
  spanish: Omit<SpanishLegalOptions, "hasContactForm"> = {},
): PageConfig[] {
  if (locale === "es") return buildSpanishLegalPages(profile, legal, { ...spanish, hasContactForm });
  return [
    buildPrivacyPolicyPage(profile, legal, hasContactForm),
    buildTermsPage(profile, legal),
    buildCookiePolicyPage(profile, legal),
  ];
}
