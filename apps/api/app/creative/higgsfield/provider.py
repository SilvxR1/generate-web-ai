"""HiggsfieldCreativeProvider — the Higgsfield boundary described in
Section 10 of the master context: premium website design, art direction,
image/video generation, and (where supported) advanced/3D-related visual
workflows.

No real integration exists yet. This repository — its code, its `.env`/
`.env.example` files, and its available MCP servers — was inspected for
an existing Higgsfield SDK, REST client, or MCP server config before
writing this file; none exists. So every method below raises
HiggsfieldNotIntegratedError rather than guessing at endpoint paths,
request/response shapes, or ever returning a fabricated success. This is
the adapter boundary Section 10 asks for when a production integration
can't yet be completed: real configuration
(HIGGSFIELD_API_KEY/HIGGSFIELD_BASE_URL, see app.config.Settings), a real
DI factory that fails loudly with 503 when unconfigured
(app.dependencies.get_higgsfield_provider), and a real, typed error path
— with the actual HTTP calls left for whoever wires this against
Higgsfield's real, documented API (see docs/architecture.md's "Higgsfield
integration status" section for what that requires).

`capabilities` declares the full set Section 10 describes Higgsfield
being capable of, deliberately not narrowed to "none": a caller attempting
one of these generation types should reach a clear, specific
HiggsfieldNotIntegratedError (surfaced by app.creative.orchestrator as a
FAILED CreativeGeneration carrying that message) rather than a generic
CreativeCapabilityNotSupportedError, which would look identical to
InternalCreativeProvider's and misleadingly suggest Higgsfield could never
support these generation types at all.
"""

from typing import NoReturn

from app.creative.errors import CreativeProviderRequestError
from app.creative.higgsfield.client import HiggsfieldClient
from app.creative.provider import CreativeGenerationResult, CreativeProvider
from app.domain.creative import CreativeBrief
from app.domain.enums import CreativeGenerationType, CreativeProviderName


class HiggsfieldNotIntegratedError(CreativeProviderRequestError):
    """Raised by every HiggsfieldCreativeProvider method today — see this
    module's docstring. Distinct from CreativeCapabilityNotSupportedError
    (which means "this provider will never support this"): Higgsfield
    genuinely could support this generation type once wired up for
    real."""


class HiggsfieldCreativeProvider(CreativeProvider):
    name = CreativeProviderName.HIGGSFIELD
    capabilities = frozenset(
        {
            CreativeGenerationType.WEBSITE_CONCEPT,
            CreativeGenerationType.WEBSITE,
            CreativeGenerationType.IMAGE,
            CreativeGenerationType.VIDEO,
            CreativeGenerationType.VISUAL_ASSET,
        }
    )

    def __init__(self, client: HiggsfieldClient) -> None:
        self._client = client

    def _not_integrated(self, generation_type: CreativeGenerationType) -> NoReturn:
        raise HiggsfieldNotIntegratedError(
            f"Higgsfield {generation_type.value} generation is not yet wired to a real API "
            "contract in this codebase (no Higgsfield SDK, REST client, or MCP server was "
            "found when this integration boundary was built). Configuration "
            "(HIGGSFIELD_API_KEY/HIGGSFIELD_BASE_URL) and provider routing are ready; only the "
            "actual HTTP call against Higgsfield's documented API is pending — see "
            "app.creative.higgsfield.client.HiggsfieldClient.request."
        )

    def generate_concept(self, brief: CreativeBrief) -> CreativeGenerationResult:
        del brief
        self._not_integrated(CreativeGenerationType.WEBSITE_CONCEPT)

    def generate_website(self, brief: CreativeBrief) -> CreativeGenerationResult:
        del brief
        self._not_integrated(CreativeGenerationType.WEBSITE)

    def generate_image(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult:
        del brief, prompt_hint
        self._not_integrated(CreativeGenerationType.IMAGE)

    def generate_video(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult:
        del brief, prompt_hint
        self._not_integrated(CreativeGenerationType.VIDEO)

    def generate_visual_asset(
        self, brief: CreativeBrief, *, prompt_hint: str | None = None
    ) -> CreativeGenerationResult:
        del brief, prompt_hint
        self._not_integrated(CreativeGenerationType.VISUAL_ASSET)
