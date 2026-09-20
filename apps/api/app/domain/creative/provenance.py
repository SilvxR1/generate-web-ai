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
from app.domain.creative.model_routing import ModelSelection
from app.domain.creative.planning import GenerationPlan
from app.domain.creative.prompt_composer import ComposedCreativePrompt
from app.domain.creative.spec import CreativeGenerationSpec

COST_SEMANTICS = "internal_estimate_not_provider_credits_or_usd"


def prompt_fingerprint(composed: ComposedCreativePrompt) -> str:
    material = "\n".join(
        [
            *composed.output_contract,
            *composed.placement,
            *composed.visual_intent,
            *composed.creative_context,
            *composed.brand_profile,
            *composed.composition_instructions,
            *composed.subject_truth,
            *composed.text_policy,
            *composed.interface_policy,
            *composed.reference_instructions,
            *composed.output_instructions,
            *composed.negative_constraints,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def plan_provenance(plan: GenerationPlan) -> dict:
    """The provider-independent part of provenance: which assets informed
    the brand profile, the reference strategy and why assets were withheld.
    Ids and reason codes only."""
    return {
        # P2.4: why THIS kind of visual — the intent (what it depicts),
        # how truthful its subject is, and which business knowledge was
        # allowed through. Field names and reason codes only: no raw business
        # text and no excluded values are stored.
        "visual_intent": plan.intent.kind.value,
        "visual_intent_reason": plan.intent.reason,
        "subject_grounding": plan.intent.grounding.value,
        "interface_policy": plan.spec.interface_policy.value,
        "creative_context": {
            "version": plan.context.version,
            "included_fields": list(plan.context.included_fields),
            "subject_category_count": len(plan.context.subject_categories),
            "excluded": [
                {"field": item.field, "reason": item.reason.value, "count": item.count}
                for item in plan.context.excluded
            ],
            "unknown": list(plan.context.unknown),
        },
        "brand_source_asset_ids": [str(asset_id) for asset_id in plan.profile.source_asset_ids],
        "brand_profile": {
            "version": plan.profile.version,
            "sources": list(plan.profile.sources),
            "palette": [color.value for color in plan.profile.palette],
            "has_official_logo": plan.profile.has_official_logo,
            "semantic_analysis": plan.profile.semantic_analysis,
        },
        "reference_strategy": {
            "policy": plan.strategy.policy.value,
            "requires_visual_reference": plan.strategy.requires_visual_reference,
            "authoritative_asset_ids": [str(asset_id) for asset_id in plan.strategy.authoritative_asset_ids],
            "withheld": [
                {"asset_id": str(item.asset_id), "reason": item.reason.value} for item in plan.strategy.withheld
            ],
        },
    }


def build_internal_provenance(plan: GenerationPlan) -> dict:
    """Provenance for a direction the InternalCreativeDirector produced from
    the same plan: no provider, no model, no generated image, and — by
    construction — nothing sent to any image model."""
    spec = plan.spec
    return {
        "purpose": spec.purpose.value,
        "brand_mode": spec.brand_mode.value,
        "creative_level": spec.creative_level.value,
        "text_policy": spec.text_policy.value,
        "provider": "internal",
        "model": None,
        "generated_image": False,
        "references": [],
        "provider_reference_asset_ids": [],
        **plan_provenance(plan),
    }


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
    plan: GenerationPlan | None = None,
    selection: ModelSelection | None = None,
) -> dict:
    provenance: dict = {
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
        # P2.3: ids only, and the two lists are deliberately distinct. An
        # asset can be a brand source (it informed the profile) without
        # ever having been sent to the image model.
        "provider_reference_asset_ids": [str(ref.asset_id) for ref in spec.reference_assets if ref.asset_id],
        "brand_source_asset_ids": [],
    }
    if plan is not None:
        provenance.update(plan_provenance(plan))
    if selection is not None:
        provenance["model_selection"] = {
            "selected": selection.model_id,
            "reason": selection.reason,
            "verified_by": selection.verified_by,
            "requirements": selection.requirements.model_dump(mode="json"),
            "rejected": [{"model_id": item.model_id, "reason": item.reason} for item in selection.rejected],
            "dropped_optional_references": selection.dropped_optional_references,
        }
    return provenance
