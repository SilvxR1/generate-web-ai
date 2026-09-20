"""Higgsfield-specific translation of a provider-independent
ComposedCreativePrompt (app.domain.creative.prompt_composer) into the
single `prompt` string Higgsfield's REST models accept. No creative
decisions are made here — only flattening. Higgsfield's request schemas
expose no separate negative-prompt field, so negative constraints are
appended as an explicit "Avoid" clause; another provider with a native
negative field would map `negative_constraints` there instead.
"""

from app.domain.creative.prompt_composer import ComposedCreativePrompt


def to_higgsfield_prompt(composed: ComposedCreativePrompt) -> str:
    sections = [
        composed.positive_prompt,
        "REFERENCES:\n" + "\n".join(composed.reference_instructions),
        "COMPOSITION:\n" + "\n".join(composed.composition_instructions),
        "OUTPUT:\n" + "\n".join(composed.output_instructions),
        "AVOID: " + "; ".join(composed.negative_constraints) + ".",
    ]
    return "\n".join(sections)
