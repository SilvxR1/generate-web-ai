"""CreativeDirectorProvider — the P2 boundary for the "explore several
genuinely different creative directions, then deepen the selected one"
workflow (P2.2/P2.3), distinct from CreativeProvider (app.creative.provider).

Why a separate ABC rather than two more methods on CreativeProvider:
CreativeProvider's five `generate_*` methods are each one concrete,
single-purpose provider call (generate one image, one video, one website
concept) — CreativeProvider.capabilities lets app.creative.orchestrator
check per-method support, and every existing implementation (Internal,
Higgsfield) implements the full set. A CreativeDirectorProvider call is a
whole *workflow* (multiple underlying calls, credit-budget-aware,
producing several CreativeDirection candidates then one deepened result),
a different shape and a different caller (app.creative.director_orchestrator,
not app.creative.orchestrator) — folding it into CreativeProvider would
force every future CreativeProvider implementation (a hypothetical OpenAI/
Replicate/Flux provider from docs/architecture.md's provider list) to
also implement a multi-step workflow even if it only ever does simple
`generate_*` calls, and would make CreativeProvider.capabilities lie
about what a single method call actually does.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import CreativeDirection
from app.domain.enums import CreativeProviderName


class CreativeDirectorProvider(ABC):
    name: ClassVar[CreativeProviderName]

    @abstractmethod
    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        """Propose several (target: ~3) genuinely different creative
        directions for `brief`'s business — never predefined template
        variants (see app.domain.creative.direction's own docstring).
        Every candidate must record real spend on `budget` (via
        `budget.record_spend`) *before* the underlying provider call that
        spend pays for — a provider that can't estimate cost ahead of a
        call must ask for one first (see
        app.creative.higgsfield.director for the real, CLI-backed
        implementation). Never fabricates cost, and never proposes a
        direction that violates `brief`'s own facts — every candidate's
        `constraints` must be traceable to `brief`."""

    @abstractmethod
    def develop_direction(
        self,
        selected: CreativeDirection,
        brief: CreativeBrief,
        assets: Sequence[CreativeBriefAsset],
        budget: CreativeBudget,
    ) -> CreativeDirection:
        """Deepen one already-selected CreativeDirection (target: ~3
        further exploration calls around it) into a richer version with
        more reference material — never a reroll of the whole
        create_directions step, and never a second, unrelated concept:
        the returned CreativeDirection's `concept`/`visual_language` must
        still describe the same direction `selected` did, only with more
        `references`/detail. Same budget-before-spend discipline as
        create_directions."""
