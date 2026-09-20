"""Content policies for generated website imagery, as concise, structured
constraints the prompt composer renders once, visually.

P2.4 rendered each policy twice (a long instruction plus a long negative
list). Long lists of interface words also PRIME an image model toward the
very things they forbid, and real experiments showed a page-like image
anyway. P2.5 fixes the cause in the scene itself (a plan whose subject and
composition do not invite text or interfaces — see scene_plan) and keeps
these as a short, final constraint set:

- TextPolicy.NO_GENERATED_TEXT: no text of any kind, pseudo-text, signs,
  labels, logos, watermarks or signatures. Words are added later, outside the
  image.
- InterfacePolicy.NO_INTERFACE_DEPICTION: never an interface, browser,
  navigation, buttons, cards, screens, webpage or mockup.

The rules live here — provider-independent — never in a provider adapter.
"""

from dataclasses import dataclass

from app.domain.creative.spec import InterfacePolicy, TextPolicy


@dataclass(frozen=True)
class PolicyRules:
    # Nouns the image must not contain. Rendered as "No a, b or c."
    forbidden: tuple[str, ...]

    def sentence(self) -> str:
        return render_prohibition(self.forbidden)


def render_prohibition(items: tuple[str, ...]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return f"No {items[0]}."
    return f"No {', '.join(items[:-1])} or {items[-1]}."


_NO_GENERATED_TEXT = PolicyRules(
    forbidden=("text", "lettering", "pseudo-text", "signs", "labels", "logos", "watermarks", "signatures")
)

_NO_INTERFACE_DEPICTION = PolicyRules(
    forbidden=("interface elements", "browser", "navigation", "buttons", "cards", "screens", "webpage", "mockup")
)


def text_rules(policy: TextPolicy) -> PolicyRules:
    return {TextPolicy.NO_GENERATED_TEXT: _NO_GENERATED_TEXT}[policy]


def interface_rules(policy: InterfacePolicy) -> PolicyRules:
    return {InterfacePolicy.NO_INTERFACE_DEPICTION: _NO_INTERFACE_DEPICTION}[policy]
