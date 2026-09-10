"""InternalCreativeProvider — wraps this codebase's own, already-working
generation system as a CreativeProvider, per Section 9 of the master
context: fallback capability, lower-cost generation, provider redundancy,
backwards compatibility.

The actual "internal generation" this codebase has today is
packages/website-generator's deterministic BusinessConfig -> SiteConfig
mapping (generateSiteConfig.ts) — TypeScript, computed client-side by
Studio (see app.publishing.service's own docstring: "the same call
Studio's own website preview uses"). This backend has no in-process way to
invoke that module directly. generate_website therefore doesn't
reimplement it in Python; it records that a generation request was
satisfied by the existing deterministic pipeline, which is the honest
description of what "internal generation" already means here (Section 20:
do not rebuild what already works) — a Python-side reimplementation would
be exactly the duplicated second code path this codebase's own
BusinessConfig.website docstring warns against for a different field.
"""

from app.creative.errors import CreativeCapabilityNotSupportedError
from app.creative.provider import CreativeGenerationResult, CreativeProvider
from app.domain.creative import CreativeBrief
from app.domain.enums import CreativeGenerationStatus, CreativeGenerationType, CreativeProviderName


class InternalCreativeProvider(CreativeProvider):
    name = CreativeProviderName.INTERNAL
    capabilities = frozenset({CreativeGenerationType.WEBSITE_CONCEPT, CreativeGenerationType.WEBSITE})

    def generate_concept(self, brief: CreativeBrief) -> CreativeGenerationResult:
        del brief
        return CreativeGenerationResult(
            status=CreativeGenerationStatus.COMPLETED,
            raw_metadata={
                "strategy": "existing_brand_and_theme",
                "note": (
                    "No separate AI concept step at this level: the concept is the business's "
                    "existing brand configuration (colors/typography/visual_style), already "
                    "captured on the CreativeBrief this request was built from."
                ),
            },
        )

    def generate_website(self, brief: CreativeBrief) -> CreativeGenerationResult:
        del brief
        return CreativeGenerationResult(
            status=CreativeGenerationStatus.COMPLETED,
            raw_metadata={
                "strategy": "deterministic_site_config",
                "note": (
                    "Website structure/content is produced by packages/website-generator's "
                    "generateSiteConfig() from the business's own BusinessConfig, not by this "
                    "provider — this result only records that the internal pipeline (not an "
                    "external creative provider) satisfied this generation request."
                ),
            },
        )

    def generate_image(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult:
        del brief, prompt_hint
        raise CreativeCapabilityNotSupportedError(
            "InternalCreativeProvider has no image-generation capability — no AI image "
            "generation exists in this codebase yet. Use a premium provider (e.g. Higgsfield) "
            "for CreativeGenerationType.IMAGE, or provide a real business photo instead."
        )

    def generate_video(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult:
        del brief, prompt_hint
        raise CreativeCapabilityNotSupportedError(
            "InternalCreativeProvider has no video-generation capability. Use a premium "
            "provider for CreativeGenerationType.VIDEO."
        )

    def generate_visual_asset(
        self, brief: CreativeBrief, *, prompt_hint: str | None = None
    ) -> CreativeGenerationResult:
        del brief, prompt_hint
        raise CreativeCapabilityNotSupportedError(
            "InternalCreativeProvider has no visual-asset-generation capability. Use a premium "
            "provider for CreativeGenerationType.VISUAL_ASSET."
        )
