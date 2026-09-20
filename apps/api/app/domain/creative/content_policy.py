"""Content policies for generated website imagery (P2.4): what an image must
never contain, expressed once as structured rules that the prompt composer
renders BOTH as positive instructions and as negative constraints.

Both forms matter: not every provider supports a negative prompt (Higgsfield's
REST models take a single `prompt`), and image models respond to positive
instructions at least as reliably as to a trailing "avoid" list. The rules
live here — provider-independent — never inside a provider adapter.

- TextPolicy.NO_GENERATED_TEXT: no readable text, no pseudo-text, no
  decorative lettering, no labels, no fake logos. Business names, headings,
  captions and prices are rendered by the website.
- InterfacePolicy.NO_INTERFACE_DEPICTION: the output is a standalone
  picture. It is never a website, webpage, browser, app or any interface —
  even when it will later be placed inside one.
"""

from dataclasses import dataclass

from app.domain.creative.spec import InterfacePolicy, TextPolicy


@dataclass(frozen=True)
class PolicyRules:
    instructions: tuple[str, ...]
    negatives: tuple[str, ...]


_NO_GENERATED_TEXT = PolicyRules(
    instructions=(
        "Do not render any text in the image: no readable words, no pseudo-text, no decorative lettering and no "
        "illegible text-like marks, including on signs, labels and packaging.",
        "Any words the finished design needs are added later, outside the image.",
    ),
    negatives=(
        "no words, letters, numbers or typography of any kind",
        "no pseudo-text, decorative lettering or text-like marks",
        "no captions, slogans, watermarks or signatures",
        "no interface or navigation labels",
        "no signs, labels or packaging containing text",
        "no fake logos or brand marks",
        "do not write or reproduce the business name",
    ),
)

_NO_INTERFACE_DEPICTION = PolicyRules(
    instructions=(
        "The output itself must NOT depict or simulate a website, webpage, browser, application, screen, dashboard "
        "or user interface of any kind, nor an ecommerce interface.",
        "It is a standalone picture: no navigation, no menus, no buttons, no cards, no forms, no page layout.",
    ),
    negatives=(
        "no website or webpage",
        "no browser or browser chrome",
        "no navigation bars or menus",
        "no user interface or app interface",
        "no buttons, cards or forms",
        "no screens, dashboards or website mockups",
        "no ecommerce interface or product grid layout",
    ),
)


def text_rules(policy: TextPolicy) -> PolicyRules:
    return {TextPolicy.NO_GENERATED_TEXT: _NO_GENERATED_TEXT}[policy]


def interface_rules(policy: InterfacePolicy) -> PolicyRules:
    return {InterfacePolicy.NO_INTERFACE_DEPICTION: _NO_INTERFACE_DEPICTION}[policy]
