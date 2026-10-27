# P2 — legal mode for a personal, non-commercial site (PROPOSAL, not implemented)

Status: proposal awaiting separate approval. Nothing here exists in code.

## Problem

GWA's Spanish publication gate (`apps/api/app/publishing/legal_readiness.py`,
C2.1/C3) always requires and prints the owner's legal name, NIF and
domicilio, plus the contact email and — with a form — the retention period
and consent. That is right for a site that promotes an economic activity
(LSSI art. 10). It cannot represent a site that genuinely has no economic
activity, where publishing a private person's NIF and home address is not
required and is itself a privacy risk. GWA has no way to record that
distinction, so today the only choices are to publish those facts or not
publish at all.

## Proposal (narrow, explicit, never inferred)

1. `legal_profile.site_nature: "economic_activity" | "personal_non_economic"`,
   default `"economic_activity"` (today's rules, unchanged for every existing
   business). Setting `personal_non_economic` requires an operator-recorded
   attestation: who, when, and the owner's statement (stored in the config's
   audit trail), never derived from words like "personal" or "portfolio".
2. Gate for `personal_non_economic`: still requires the owner's name
   (controller identity, RGPD art. 13), a privacy contact email, and with a
   form the retention period and consent. Does not require NIF or domicilio.
   Every other check (staleness, QA, consent field on forms) unchanged.
3. Legal pages for that mode: the privacy notice names the controller and
   contact; "Aviso legal" becomes "Información sobre este sitio" without
   NIF/domicilio lines (omitted, never shown as "no facilitado").
4. JSON-LD for that mode: `WebSite` (name, url) only — no `LocalBusiness`/
   `Store`, no `Offer`s, no address or phone.
5. Tests: default behaviour byte-identical for existing businesses (plan and
   SiteConfig pins unchanged); the mode cannot be set without the
   attestation; a site whose copy or config shows prices, checkout or
   quotations fails the gate in that mode.

## Not covered by this proposal

Whether a given site qualifies. That is a legal question for the owner (and,
ideally, a Spanish legal professional): if the owner sells or takes paid
commissions through any channel, the site promotes an economic activity and
the default mode applies.
