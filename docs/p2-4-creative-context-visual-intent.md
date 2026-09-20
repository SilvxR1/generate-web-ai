# P2.4 — Creative context and visual intent

> **Follow-up: P2.5.** Experiment 4 (this PR's real test) still produced a page-like layout: `VisualIntent` is not a
> concrete scene. See [p2-5-visual-scene-planning.md](p2-5-visual-scene-planning.md). The prompt sections described
> below were replaced by scene sentences plus a short constraints block.

## Why

P2.3 fixed reference handling and routing: Experiment 3 sent no logo and no reference to `soul/standard`. The result was
a **fake webpage** — navigation, headings, buttons, a product grid, invented objects. Two causes, both ours:

1. **Operational business text reached the image prompt.** The prompt carried the raw `description` ("no dispone de
   página web", "Instagram", "ecommerce", "catálogo … contacto"), an `ecommerce` industry label and the target-customer
   text ("visitantes llegue desde Instagram"). A text-to-image model with nothing else to depict draws what the words
   describe.
2. **HERO said where, not what.** `AssetPurpose.HERO` was rendered as "the hero image at the top of the business's
   website", plus composition rules mentioning a heading and call-to-action, with thin anti-interface constraints. Nothing
   said what the picture should *depict*, so the model depicted the website.

## Architecture

```
Business profile ──► CreativeContext         only verified, visually useful facts (+ what was excluded and why)
BusinessAssets ┐
BrandVisualProfile ├──► VisualIntent         what to depict (separate from AssetPurpose = where it is used)
CreativeContext ┘
                          │
   GenerationPlan (spec, profile, context, intent, strategy, requirements)
                          │
   CreativePromptComposer ──► reference strategy ──► model router ──► provider adapter
```

| Module | Role |
| --- | --- |
| `domain/creative/creative_context.py` | `CreativeContext`, `build_creative_context` |
| `domain/creative/visual_intent.py` | `VisualIntent`, `SubjectGrounding`, `resolve_visual_intent` |
| `domain/creative/content_policy.py` | text and interface rules (instructions + negatives) |
| `domain/creative/prompt_composer.py` | the ten-section composer |
| `domain/creative/planning.py` | `GenerationPlan` now carries `context` and `intent` |

All pure domain code. The Higgsfield adapter only flattens and sends; none of this lives in it.

## CreativeContext

Built from **structured fields only**:

- **Included:** the industry label *only if it names something visual* (`restaurant`, `hotel`, `clinic`,
  `home_renovation`, `real_estate`); and service **names** that pass the label filter (max 4).
- **Excluded, with a reason code:** free-text `description`, `target_customers`, service descriptions (may carry
  operational/digital context); `ecommerce` / `agency` / `b2b_services` / `other` industry labels (a business model, not a
  subject); tagline, location, reviews (not used for imagery); the business name (the website renders it, not the
  image); website/lead/integration configuration.
- **Unknown:** anything with no verified visual information — recorded as unknown, never filled in.

Contact details, URLs, social handles and integrations never reach the brief at all; the label filter additionally
drops any *service label* containing an email, phone, URL or handle pattern.

### Limits of the free-text boundary (please read)

Free-text prose is **not filtered, it is not forwarded**. No heuristic can reliably understand arbitrary prose, so the
safe rule is exclusion. Cost: a fact that exists only inside a description (for example a business that says "reformas
de baños" in prose but has no structured services) yields no subject, and the image becomes abstract/atmospheric.

The one term filter that exists (`_OPERATIONAL_TERMS`) is applied only to short service *labels*, only removes, and is a
conservative list — not a substitution pass and not language understanding. It can miss a digital term it does not list
and can drop a legitimate label that contains one (for example a physical "app" product). Both errors fail toward
excluding. A future extractor for useful facts in prose would plug in behind this boundary with its own provenance.

## VisualIntent

Small on purpose — only what the current product can defend:

| Intent | Meaning |
| --- | --- |
| `product_grounded` | a real product from a real reference (PRODUCT purpose) |
| `subject_editorial` | a conceptual, category-level depiction of verified offerings |
| `abstract_brand` | shape/texture/light expressing the brand profile; no literal subject |
| `atmospheric` | mood through light, colour and space; no literal subject (the safe default) |

Resolution is deterministic (no LLM):

- PRODUCT: real product image present → `product_grounded`/grounded; otherwise grounding `unknown`, and the P2.3 strategy
  still reports the request unsatisfiable (never invents a product).
- BACKGROUND, TEXTURE: never a subject → `abstract_brand` with a brand profile, else `atmospheric`.
- HERO, SECTION, EDITORIAL: verified subject categories → `subject_editorial`; else `abstract_brand` if a brand profile
  exists (not for `NEW_DIRECTION`); else `atmospheric`.

`purpose` is placement; `intent` is subject. The same HERO resolves differently with different evidence.

## Subject grounding

`grounded` (from a real reference) · `conceptual` (generated, representational, makes no claim about real products,
projects, customers or premises — abstract images and category-level depictions) · `unknown` (required subject
information is missing). Recorded in provenance so a future UI can label conceptual imagery as such. Category-level
depiction of a verified offering ("Llaveros de lana") is conceptual; it is never presented as a real Cositas product.

## HERO semantics and interface/text policy

The prompt now says: *create one standalone visual asset; it will later be placed inside a website hero section; the
image is only the picture, not that page; it must not depict or simulate a website, browser, application or interface.*
Composition rules no longer mention headings or calls-to-action; they ask for calm negative space "so the picture can
later sit beneath other page content".

`NO_GENERATED_TEXT` is strengthened (no readable text, pseudo-text, decorative lettering, interface or navigation
labels, text on signs/packaging, fake logos) and a new `InterfacePolicy.NO_INTERFACE_DEPICTION` forbids website, webpage,
browser, navigation, menus, UI, buttons, cards, forms, screens, dashboards, mockups and ecommerce interfaces. Both live in
`content_policy.py` as structured rules rendered **twice** — as positive instructions and as negative constraints —
because Higgsfield's REST models take a single `prompt` and positive instructions are at least as effective as an avoid
list.

## Prompt sections

OUTPUT CONTRACT · PLACEMENT · VISUAL INTENT · VERIFIED CREATIVE CONTEXT · BRAND VISUAL PROFILE · COMPOSITION · SUBJECT
TRUTH · TEXT POLICY · INTERFACE POLICY · REFERENCES · OUTPUT · AVOID. Raw business descriptions are never included.
Exploration angles are intent-aware (still-life/lifestyle variations for `subject_editorial`; abstract/atmospheric
variations otherwise).

## Provenance

`generation_metadata.creative_spec` (no migration) adds `visual_intent`, `visual_intent_reason`, `subject_grounding`,
`interface_policy` and `creative_context` (version, included field names, subject-category *count*, excluded
`{field, reason, count}` and unknown). Field names and reason codes only — never raw business text, excluded values,
presigned URLs or secrets. Prompt version is now `p2.4-v1`. Studio shows "Visual intent" and "Subject grounding".

## Unchanged from P2.3

Logo = brand source only; `provider_reference_asset_ids` stays `[]` for HERO; the capability router picks
`soul/standard` for a no-reference request and `soul/reference` remains available for genuine reference-conditioned cases;
PRODUCT requires a real product reference; fallback stays explicit; `hard_limit` still permits one submission with no
POST retry; estimated units remain an internal estimate.

## Known risks and deferred

- The prompt is longer (about 3.5k characters against about 2.7k) because policies appear as instructions and as
  negatives. Higgsfield's prompt-length limit for `soul/standard` is not documented; if one exists, a rejection would
  surface as a structured provider error.
- Whether the new prompt actually removes the mockup behaviour is untested against the real model (needs another real
  call — a separate decision).
- Extracting useful facts from free-text descriptions; palette extraction and semantic brand analysis; a deterministic
  logo overlay in website generation; real provider cost accounting; visual QA for unwanted text/UI.
