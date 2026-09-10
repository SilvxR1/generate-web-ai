/**
 * Business-brief vs. customer-facing copy separation (LR-08). Everything
 * a Business Analyzer or an operator writes into `BusinessProfile.description`
 * is meant to help the *platform* understand the business — it was never
 * reviewed as visitor-facing marketing copy. Left unfiltered, sentences
 * like "the business currently has no website yet" or "no ecommerce/cart
 * in this first version" end up published verbatim as hero copy, about-
 * section copy, and SEO meta description (see blocks.ts/seo.ts, the three
 * call sites that read `profile.description`).
 *
 * This module is a deterministic, no-AI safety net — it runs even when no
 * paid/LLM creative provider is configured, matching the rest of this
 * package's "fixed mapping from real facts" design. It does not try to
 * rewrite or improve copy (that would risk inventing claims); it only
 * removes sentences that read as internal scoping/strategy commentary
 * rather than a fact about the business a visitor would care about.
 */

// Each pattern matches a whole sentence that is *about the project/website
// itself* (scope, implementation status, objectives) rather than about the
// business's product or service. Deliberately phrase-based, not single
// keywords: "no ecommerce" alone would also strike a legitimate sentence
// like "no ecommerce hassle — just message us", so every pattern requires
// enough surrounding context to be unambiguous internal-strategy language.
const INTERNAL_STRATEGY_PATTERNS: RegExp[] = [
  /\bno\s+(previous\s+|existing\s+)?website\b.{0,40}\byet\b/i,
  /\b(currently\s+)?has\s+no\s+website\b/i,
  /\bmain\s+presence\s+is\s+instagram\b/i,
  /\bno\s+ecommerce\b.{0,40}\b(cart|payment|checkout)\b/i,
  /\b(cart|checkout|payment)\b.{0,40}\bthis\s+first\s+version\b/i,
  /\bnot\s+in\s+this\s+first\s+version\b/i,
  /\bin\s+(this\s+)?(first\s+)?v1\b/i,
  /\bconversion\s+objective\b/i,
  /\bseo\s+objective\b/i,
  /\bimplementation\s+constraint\b/i,
  /\bdo\s+not\s+invent\b/i,
  /\boperator\s+note\b/i,
  /\bmigration\s+note\b/i,
  /\bno\s+google\s+reviews?\b/i,
  /\bcatalog(ue)?\s*\/\s*portfolio\s*\+\s*(contact|order|enquiry)\b/i,
  /\bobjective\s+is\s+to\s+create\s+a\s+professional\s+digital\s+presence\b/i,
  /\b(this|the)\s+website('?s)?\s+(aims?|goal|objective)\b/i,
  /\bwe\s+(are\s+)?build(ing)?\s+(a\s+|this\s+)?website\b/i,
];

/** Splits on sentence-ending punctuation, keeping the punctuation with
 * the sentence it closes, and drops empty fragments (e.g. from a
 * trailing period). Good enough for short business-profile prose — not a
 * general-purpose NLP sentence splitter. */
function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length > 0);
}

function isInternalStrategySentence(sentence: string): boolean {
  return INTERNAL_STRATEGY_PATTERNS.some((pattern) => pattern.test(sentence));
}

/**
 * Removes sentences that read as internal briefing/strategy commentary
 * rather than a customer-facing fact. Returns `undefined` when nothing
 * publishable is left (never an empty string masquerading as real copy)
 * so callers fall through to their own generic fallback, exactly like an
 * absent description already does.
 */
export function sanitizeCustomerCopy(text: string | null | undefined): string | undefined {
  if (!text) return undefined;
  const trimmed = text.trim();
  if (trimmed.length === 0) return undefined;

  const kept = splitSentences(trimmed).filter((sentence) => !isInternalStrategySentence(sentence));
  const result = kept.join(" ").trim();
  return result.length > 0 ? result : undefined;
}
