"""Higgsfield-specific translation of a provider-independent
ComposedCreativePrompt (app.domain.creative.prompt_composer) into the
single `prompt` string Higgsfield's REST models accept. No creative
decisions are made here — only flattening: the scene sentences, then any
reference instructions, then the short constraints. Higgsfield's request
schemas expose no separate negative-prompt field, so the prohibitions travel
as the final constraint sentences; a provider with a native negative field
would map `negative_constraints` there instead.
"""

from app.domain.creative.prompt_composer import ComposedCreativePrompt


def to_higgsfield_prompt(composed: ComposedCreativePrompt) -> str:
    blocks = [
        " ".join(composed.scene),
        " ".join(composed.reference_instructions),
        " ".join(composed.constraints),
    ]
    return "\n".join(block for block in blocks if block)
