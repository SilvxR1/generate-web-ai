# P2.5 — Visual scene planning and generation contracts

## Why

Each real Cositas experiment removed one cause and exposed the next:

| Experiment | Change | Result |
| --- | --- | --- |
| 1 (P2.1), 2 (P2.2) | logo sent to `soul/reference` | logo recreated, name generated |
| 3 (P2.3) | no logo, `soul/standard`, but raw description in the prompt | a fake webpage |
| 4 (P2.4) | description removed, `VisualIntent = subject_editorial` | still a page-like layout with pseudo-text |

Experiment 4's prompt listed **all four verified offerings** (their labels appeared as text inside the image), explained
our own "website hero" placement, and repeated long interface vocabularies. `subject_editorial` is domain metadata, not
a scene. The model still had to invent the subject, environment, composition, framing, lighting, layout and amount of
negative space — and it invented a page.

## Architecture

```
CreativeContext ─► VisualIntent ─► VisualSubject ─► VisualScenePlan ─► GenerationContract
   (verified)       (what kind)     (one focus)      (how depicted)      (validated before spend)
                                                                              │
                        CreativePromptComposer ─► reference strategy ─► capability router ─► provider adapter
```

| Concept | Answers | Module |
| --- | --- | --- |
| `AssetPurpose` | where/how the asset will be used | `enums.py` |
| `VisualIntent` | what broad kind of visual | `visual_intent.py` |
| `VisualSubject` | what the image focuses on | `visual_subject.py` |
| `VisualScenePlan` | how that subject is depicted | `scene_plan.py` |
| `GenerationContract` | everything a provider must satisfy, inspectable before execution | `generation_contract.py` |

All provider-independent and deterministic (no LLM, no image analysis). The Higgsfield adapter builds and validates the
contract, sends, polls and parses; it selects no subject, invents no scene and interprets no business context.

## VisualSubject

One narrow focus, never a list. Order: a grounded real reference (PRODUCT) → a **material family** supported by the
verified service labels → a **single** verified category → none (abstract/atmospheric).

Material families are a small, conservative lexicon of stems (yarn/crochet, ceramics, woodcraft, leather craft). A family is
chosen only when the verified *labels themselves* contain its stems (never from the business type or from prose) and the
family with the most supporting labels wins. For Cositas, "Amigurumis artesanales hechos a mano" and "Llaveros de lana"
support `crochet and yarn craft`; "Tartas de pañales" and "Cestas personalizadas" do not, and are not combined into the
subject. Grounding stays `conceptual`; a family is depicted with **generic materials, never an identifiable finished
product**, so the image can never imply real Cositas inventory. The lexicon can miss a family (falling back to one
verified category) but cannot create one the labels do not support.

## VisualScenePlan

Immutable, structured, and limited to fields that change what is drawn: medium, primary subject, subject treatment,
environment, composition, subject side, placement, negative space, framing, lighting, depth, material emphasis, brand
guidance (only configured brand information), aspect ratio, crop-safe area, grounding, `requires_fidelity`, and forbidden
elements (collage, grid, multi-panel layout, shelves or storefront, packaging, product display — things that naturally
invite text or interface layouts).

Placement becomes composition. HERO → 16:9, single continuous scene, subject biased to the right half, generous
uncluttered negative space on the left, key detail away from the edges. That matches the current hero block (copy left,
image right). BACKGROUND/TEXTURE have no dominant subject; PRODUCT centres one product fully in frame. Creative level
changes lighting; `NEW_DIRECTION` drops brand guidance. Three deterministic variants (mirrored side, different framing)
replace the old free-text exploration angles.

## Removing web semantics from the provider prompt

Internally the purpose stays HERO. Externally the prompt never says "website", "hero", "page" or "ecommerce" — those
appear only inside the final prohibitions ("No … webpage or mockup"). Business name, description and target-customer text
never reach it. The prompt is now scene sentences, any reference instructions, and one short constraints block. For the
Cositas HERO request it is about 870 characters (P2.4: about 3,470) and reads like a photographer's brief. Rationale
lives in provenance, not in the prompt.

## GenerationContract and validation before spend

The contract holds purpose, intent, subject, grounding, scene, text and interface policy, brand mode and level, reference
policy and requirement, the references actually selected, and output requirements — no provider or model. It is validated
before any submission; an invalid contract raises before any spend and degrades through the existing explicit fallback.

Rejected states: PRODUCT without grounding; a scene needing fidelity but only conceptual; a scene description that itself
asks for an interface/page/website or for text/signs/logos; a reference policy that conflicts with the selected
references; a required reference missing; a brand mark as a provider reference; an aspect ratio no candidate model
supports. This is structural/semantic validation, **not** visual QA, and gives no guarantee about the eventual image.

## Unchanged

Logo = brand source only; no provider reference for HERO; capability router (`soul/standard` for no-reference requests,
`soul/reference` for genuine reference-conditioned jobs); PRODUCT requires a real product image; explicit fallback;
`hard_limit=2.0` permits one submission with no POST retry; `estimated_generation_units` remains an internal estimate;
BrandVisualProfile unchanged (no logo analysis or palette extraction).

## Provenance and Studio

`generation_metadata.creative_spec` adds `visual_subject`, `visual_subject_source`, `visual_subject_reason`,
`scene_plan_version`, a bounded `scene_plan` summary (medium, primary subject, side, composition, framing, aspect,
`requires_fidelity`) and `generation_contract_version`; prompt version is `p2.5-v1`. No migration, no URLs or secrets.
Studio adds read-only *Visual subject* and *Composition* rows to the preview; there is no scene-planning form.

## Known risks and deferred

- Whether a concrete scene actually stops the model drawing a page is untested against the real model (needs another
  real call — a separate decision).
- The hero block crops its image to 4:5 in a two-column layout while HERO generates 16:9; the crop-safe wording helps but
  the aspect ratio for that layout is a website-generation decision.
- The material-family lexicon is small; more families or a real analyser can extend it. Brand Intelligence (palette,
  logo analysis) is P2.6.
