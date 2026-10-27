/**
 * C2.1 — Spanish legal pages for a client site (locale "es"): Aviso Legal
 * (LSSI-CE art. 10), Política de Privacidad (RGPD art. 13) and Política de
 * Cookies. Same hard rule as legal.ts: every fact comes from
 * BusinessConfig, and a missing one renders as PENDING — never a guessed
 * NIF, address, legal identity, legal basis or retention period, and never
 * a claim about who owns the site's photos or that a lawyer reviewed the
 * text.
 *
 * `spanishLegalPendingFacts` lists what is still missing. While anything
 * is, each page carries a visible "pending" notice, and the API refuses a
 * commercial publication (app.publishing.legal_readiness mirrors this
 * list). Once everything is provided the pages carry no notice at all.
 */
import type { BusinessProfile, LeadManagementConfig, LegalProfile } from "@generate-web-ai/business-config-types";
import type { ContactFormPrivacyNoticeConfig, PageConfig } from "@generate-web-ai/site-config";

export const SPANISH_LEGAL_PATHS = {
  legalNotice: "/aviso-legal",
  privacy: "/privacidad",
  cookies: "/cookies",
} as const;

export const PENDING = "Pendiente de completar por el titular.";

const PENDING_NOTICE =
  "Algunos datos de esta página están pendientes de completar por el titular del sitio web.";

export interface SpanishLegalOptions {
  hasContactForm: boolean;
  /** The form's field names, so the policy lists exactly what is collected. */
  formFields?: readonly string[];
  leadManagement?: LeadManagementConfig;
}

/** Stable ids, mirrored by app.publishing.legal_readiness.SPANISH_LEGAL_FACTS. */
export type SpanishLegalFact =
  | "legal_name"
  | "tax_id"
  | "address"
  | "contact_email"
  | "data_retention"
  | "legal_basis";

function present(value: string | null | undefined): value is string {
  return Boolean(value && value.trim());
}

function holder(legal: LegalProfile | undefined): string | undefined {
  return present(legal?.legal_name) ? legal.legal_name.trim() : undefined;
}

function address(legal: LegalProfile | undefined): string | undefined {
  const a = legal?.address;
  if (!a) return undefined;
  const text = [a.street_address, a.postal_code, a.locality, a.region, a.country]
    .filter((part): part is string => present(part))
    .join(", ");
  return text || undefined;
}

function contactEmail(profile: BusinessProfile, legal: LegalProfile | undefined): string | undefined {
  if (present(legal?.privacy_contact_email)) return legal.privacy_contact_email.trim();
  return present(profile.contact?.email) ? profile.contact.email.trim() : undefined;
}

export function spanishLegalPendingFacts(
  profile: BusinessProfile,
  legal: LegalProfile | undefined,
  options: SpanishLegalOptions,
): SpanishLegalFact[] {
  const missing: SpanishLegalFact[] = [];
  if (!holder(legal)) missing.push("legal_name");
  if (!present(legal?.tax_id)) missing.push("tax_id");
  if (!address(legal)) missing.push("address");
  if (!contactEmail(profile, legal)) missing.push("contact_email");
  if (options.hasContactForm) {
    if (!present(legal?.data_retention)) missing.push("data_retention");
    // Consent is the only legal basis this platform can state truthfully,
    // because it is the only one the form itself enforces.
    if (!options.leadManagement?.consent_required) missing.push("legal_basis");
  }
  return missing;
}

const FIELD_NAMES: Record<string, string> = {
  name: "nombre",
  email: "correo electrónico",
  phone: "teléfono",
  message: "el mensaje que escribas",
  service: "el servicio que te interesa",
};

function collectedData(fields: readonly string[] | undefined): string {
  const names = (fields ?? []).map((field) => FIELD_NAMES[field]).filter((name): name is string => Boolean(name));
  return names.length > 0 ? names.join(", ") : "los datos que introduzcas en el formulario";
}

function page(path: string, heading: string, pending: boolean, sections: { heading: string; body: string }[]): PageConfig {
  return {
    path,
    blocks: [
      {
        type: "legal_text",
        content: { heading, ...(pending ? { disclaimer: PENDING_NOTICE } : {}), sections },
      },
    ],
  };
}

function identityBody(profile: BusinessProfile, legal: LegalProfile | undefined): string {
  const lines = [
    `Titular: ${holder(legal) ?? PENDING}`,
    `NIF: ${present(legal?.tax_id) ? legal.tax_id.trim() : PENDING}`,
    `Domicilio: ${address(legal) ?? PENDING}`,
    `Correo electrónico: ${contactEmail(profile, legal) ?? PENDING}`,
  ];
  if (present(legal?.registration_number)) lines.push(`Datos registrales: ${legal.registration_number.trim()}`);
  return lines.join("\n\n");
}

export function buildSpanishLegalPages(
  profile: BusinessProfile,
  legal: LegalProfile | undefined,
  options: SpanishLegalOptions,
): PageConfig[] {
  const pending = spanishLegalPendingFacts(profile, legal, options).length > 0;
  const email = contactEmail(profile, legal) ?? PENDING;
  const consent = Boolean(options.leadManagement?.consent_required);
  const processors = (legal?.data_processors ?? []).filter(present);

  const legalNotice = page(SPANISH_LEGAL_PATHS.legalNotice, "Aviso legal", pending, [
    { heading: "Titular del sitio web", body: identityBody(profile, legal) },
    {
      heading: "Objeto",
      body: `Este sitio web presenta la actividad de ${profile.name} y permite ponerse en contacto con su titular.`,
    },
    {
      heading: "Privacidad y cookies",
      body:
        "El tratamiento de datos personales se explica en la Política de privacidad y el uso del " +
        "almacenamiento del navegador, en la Política de cookies.",
    },
  ]);

  const privacySections = [{ heading: "Responsable del tratamiento", body: identityBody(profile, legal) }];
  if (options.hasContactForm) {
    privacySections.push(
      {
        heading: "Qué datos tratamos y para qué",
        body:
          `Si nos escribes mediante el formulario de contacto tratamos ${collectedData(options.formFields)} ` +
          "con la única finalidad de atender tu consulta y responderte. Estos datos no se usan para publicidad ni " +
          "para estadísticas.\n\n" +
          "Tu mensaje se guarda en la plataforma que aloja este sitio y se envía por email al titular para que " +
          "pueda responderte. Puedes recibir un email automático que confirma su recepción.",
      },
      {
        heading: "Legitimación",
        body: consent
          ? "Tu consentimiento, que prestas al marcar la casilla del formulario. Puedes retirarlo en cualquier " +
            "momento escribiendo al correo electrónico indicado."
          : PENDING,
      },
      {
        heading: "Conservación",
        body: present(legal?.data_retention) ? legal.data_retention.trim() : PENDING,
      },
    );
  } else {
    privacySections.push({
      heading: "Qué datos tratamos",
      body: "Este sitio web no incluye ningún formulario para enviarnos datos personales.",
    });
  }
  privacySections.push(
    {
      heading: "Proveedores con acceso a los datos",
      body: processors.length > 0 ? processors.join(", ") : PENDING,
    },
    {
      heading: "Tus derechos",
      body:
        "Puedes solicitar el acceso, la rectificación o la supresión de tus datos, así como la limitación " +
        `u oposición a su tratamiento y su portabilidad, escribiendo a ${email}.\n\n` +
        "También puedes presentar una reclamación ante la Agencia Española de Protección de Datos (www.aepd.es).",
    },
  );
  const privacy = page(SPANISH_LEGAL_PATHS.privacy, "Política de privacidad", pending, privacySections);

  const cookies = page(SPANISH_LEGAL_PATHS.cookies, "Política de cookies", pending, [
    {
      heading: "Qué utiliza este sitio",
      body:
        "El código de este sitio web no crea cookies. Guarda tu elección sobre privacidad en el almacenamiento " +
        "local de tu navegador para no volver a preguntarte.\n\n" +
        "Si aceptas la categoría «Analítica», el sitio envía al servidor del titular eventos de uso sin " +
        "identificadores personales (por ejemplo, visitas a la página o pulsaciones en los botones de contacto). " +
        "Si no la aceptas, no se envía ninguno.",
    },
    {
      heading: "Cómo cambiar tu elección",
      body: "Puedes cambiarla en cualquier momento desde el enlace «Preferencias de privacidad» del pie de página.",
    },
  ]);

  return [legalNotice, privacy, cookies];
}

/** First-layer notice under the contact form: the owner's own text when
 * provided, otherwise a short summary built only from known facts. */
export function buildSpanishFirstLayerNotice(
  legal: LegalProfile | undefined,
  leadManagement: LeadManagementConfig | undefined,
): ContactFormPrivacyNoticeConfig {
  const linkLabel = "Más información en la política de privacidad.";
  if (present(legal?.first_layer_notice)) {
    return { text: legal.first_layer_notice.trim(), linkLabel, href: SPANISH_LEGAL_PATHS.privacy };
  }
  const parts = [
    `Responsable: ${holder(legal) ?? "pendiente de completar por el titular"}.`,
    "Finalidad: atender tu consulta.",
  ];
  if (leadManagement?.consent_required) parts.push("Legitimación: tu consentimiento.");
  parts.push("Derechos: acceso, rectificación, supresión y otros.");
  return { text: parts.join(" "), linkLabel, href: SPANISH_LEGAL_PATHS.privacy };
}
