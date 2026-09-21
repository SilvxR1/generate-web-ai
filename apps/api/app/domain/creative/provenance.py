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
from app.domain.creative.brand_profile import BrandVisualProfile, PaletteSource
from app.domain.creative.generation_contract import GenerationContract
from app.domain.creative.model_routing import ModelSelection
from app.domain.creative.planning import GenerationPlan
from app.domain.creative.prompt_composer import ComposedCreativePrompt
from app.domain.creative.scene_plan import VisualScenePlan
from app.domain.creative.spec import CreativeGenerationSpec

COST_SEMANTICS = "internal_estimate_not_provider_credits_or_usd"


def prompt_fingerprint(composed: ComposedCreativePrompt) -> str:
    material = "\n".join(
        [
            *composed.scene,
            *composed.reference_instructions,
            *composed.constraints,
            *composed.negative_constraints,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def scene_summary(scene: VisualScenePlan) -> dict:
    """A bounded, structured summary of the scene — enough to explain how the
    subject was depicted without duplicating the prompt."""
    return {
        "version": scene.version,
        "medium": scene.medium,
        "primary_subject": scene.primary_subject,
        "subject_side": scene.subject_side.value,
        "composition": scene.composition,
        "framing": scene.framing,
        "aspect_ratio": scene.aspect_ratio,
        "requires_fidelity": scene.requires_fidelity,
        # P2.6: which brand colors reached the scene as styling (values only;
        # the guidance sentence itself lives in the prompt, not provenance).
        "brand_palette": list(scene.brand_palette),
    }


def brand_profile_provenance(profile: BrandVisualProfile) -> dict:
    """What Brand Intelligence knew and how it knew it (P2.6): was a palette
    configured / measured / unavailable / not performed / failed, which
    assets it came from, the method and the measured properties. Hex values,
    ids and codes only — never image bytes, URLs or pixel data."""
    palette_sources = {color.source.value for color in profile.palette}
    return {
        "version": profile.version,
        "sources": list(profile.sources),
        "palette": [color.value for color in profile.palette],
        "palette_status": profile.palette_status.value,
        "palette_source": palette_sources.pop() if len(palette_sources) == 1 else None,
        "palette_method": profile.palette_method,
        "analysis_version": profile.analysis_version,
        "analysis_failure": profile.analysis_failure,
        "measured_asset_ids": [str(asset_id) for asset_id in profile.measured_asset_ids],
        "measured_palette": [
            {
                "hex": color.value,
                "role": color.role,
                "foreground_share": color.foreground_share,
                "luminance": color.luminance,
                "tone": color.tone,
                "saturation_band": color.saturation_band,
            }
            for color in profile.palette
            if color.source is PaletteSource.ASSET_EXTRACTION
        ],
        "excluded_colors": [item.model_dump(mode="json") for item in profile.excluded_colors],
        # Configured (never inferred) values, so "not configured" is explicit.
        "typography": "configured" if profile.typography_hints else "not_configured",
        "typography_hints": list(profile.typography_hints),
        "visual_style": profile.visual_style,
        "has_official_logo": profile.has_official_logo,
        "semantic_analysis": profile.semantic_analysis,
    }


def plan_provenance(plan: GenerationPlan, contract: GenerationContract | None = None) -> dict:
    """The provider-independent part of provenance: which assets informed
    the brand profile, the reference strategy and why assets were withheld.
    Ids and reason codes only."""
    contract = contract or plan.contract
    return {
        # P2.5: the single visual subject, the scene that depicts it and the
        # contract it was validated under.
        "visual_subject": plan.subject.label,
        "visual_subject_source": plan.subject.source.value,
        "visual_subject_reason": plan.subject.reason,
        "scene_plan_version": contract.scene.version,
        "scene_plan": scene_summary(contract.scene),
        "generation_contract_version": contract.version,
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
        "brand_profile": brand_profile_provenance(plan.profile),
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
    contract: GenerationContract | None = None,
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
        provenance.update(plan_provenance(plan, contract))
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
