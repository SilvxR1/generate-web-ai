"""Higgsfield-specific translation of a provider-independent
ComposedCreativePrompt (app.domain.creative.prompt_composer) into the
single `prompt` string Higgsfield's REST models accept. No creative
decisions are made here — only flattening, section by section in the
composer's own order. Higgsfield's request schemas expose no separate
negative-prompt field, so negative constraints are appended as an explicit
"Avoid" clause; because of that, the same rules also appear as positive
instructions inside the sections (TEXT POLICY / INTERFACE POLICY). Another
provider with a native negative field would map `negative_constraints`
there instead.
"""

from app.domain.creative.prompt_composer import ComposedCreativePrompt


def to_higgsfield_prompt(composed: ComposedCreativePrompt) -> str:
    ordered = (
        ("OUTPUT CONTRACT", composed.output_contract),
        ("PLACEMENT", composed.placement),
        ("VISUAL INTENT", composed.visual_intent),
        ("VERIFIED CREATIVE CONTEXT", composed.creative_context),
        ("BRAND VISUAL PROFILE", composed.brand_profile),
        ("COMPOSITION", composed.composition_instructions),
        ("SUBJECT TRUTH", composed.subject_truth),
        ("TEXT POLICY", composed.text_policy),
        ("INTERFACE POLICY", composed.interface_policy),
        ("REFERENCES", composed.reference_instructions),
        ("OUTPUT", composed.output_instructions),
    )
    sections = [f"{title}:\n" + "\n".join(lines) for title, lines in ordered if lines]
    sections.append("AVOID: " + "; ".join(composed.negative_constraints) + ".")
    return "\n".join(sections)
