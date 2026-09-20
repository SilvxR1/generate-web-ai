"""Provenance for a generated creative asset (P2.2): enough to explain
later why it was generated and with what, persisted inside the existing
CreativeDirection.generation_metadata JSON (no schema migration).

Never contains presigned R2 URLs, provider result URLs, credentials or
raw provider payloads — reference assets are recorded by id and role
only, and the composed prompt by version and hash, never as text.

COST SEMANTICS: `estimated_generation_units` is this platform's own
internal budgeting estimate. It is NOT Higgsfield credits and NOT USD —
the first real production generation reported 2.0 internally while the
provider balance moved by roughly $0.06. Real provider cost accounting is
a deliberate follow-up (docs/p2-2-creative-prompt-composition.md).
"""

import hashlib

from app.domain.creative.asset_validation import AssetValidationResult
from app.domain.creative.prompt_composer import ComposedCreativePrompt
from app.domain.creative.spec import CreativeGenerationSpec

COST_SEMANTICS = "internal_estimate_not_provider_credits_or_usd"


def prompt_fingerprint(composed: ComposedCreativePrompt) -> str:
    material = "\n".join(
        [
            composed.positive_prompt,
            *composed.reference_instructions,
            *composed.composition_instructions,
            *composed.output_instructions,
            *composed.negative_constraints,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_creative_provenance(
    *,
    spec: CreativeGenerationSpec,
    composed: ComposedCreativePrompt,
    validation: AssetValidationResult,
    provider: str,
    model: str,
    job_id: str | None,
    estimated_generation_units: float,
    angle: str,
) -> dict:
    return {
        "purpose": spec.purpose.value,
        "brand_mode": spec.brand_mode.value,
        "creative_level": spec.creative_level.value,
        "text_policy": spec.text_policy.value,
        "angle": angle,
        "prompt_version": composed.version,
        "prompt_fingerprint": prompt_fingerprint(composed),
        "references": [
            {
                "asset_id": str(ref.asset_id) if ref.asset_id else None,
                "usage": ref.usage.value,
                "asset_kind": ref.asset_kind.value if ref.asset_kind else None,
                "asset_category": ref.asset_category.value if ref.asset_category else None,
                "source": ref.source,
            }
            for ref in spec.reference_assets
        ],
        "provider": provider,
        "model": model,
        "job_id": job_id,
        "estimated_generation_units": estimated_generation_units,
        "cost_semantics": COST_SEMANTICS,
        "validation": validation.model_dump(mode="json"),
    }
