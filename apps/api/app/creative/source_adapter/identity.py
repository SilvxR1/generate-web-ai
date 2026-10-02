"""R5.2 — source <-> BusinessTruth identity check.

An export declares whose site it is in a few deterministic places: the page
metadata title (app-meta `og_title`), `og:site_name`, the web app manifest
`name`/`short_name`, and a JSON-LD organization/business `name`. This module
compares those declarations with BusinessTruth and classifies the evidence:

- ABSENT: the export declares no identity -> no finding;
- COMPATIBLE: BusinessTruth's name appears in the export's text, or a
  declaration shares a distinctive word with it -> no finding (a redesign
  may restyle the name; it does not have to match exactly);
- AMBIGUOUS: the export declares another name but some BusinessTruth facts
  (city, services) do appear -> `source_identity_unconfirmed` (info);
- CONTRADICTORY: the export declares another name AND none of BusinessTruth's
  services appear AND (the city is absent OR two independent declarations
  agree on the other name) -> `source_identity_conflict` (review). A review
  finding blocks the build until an operator approves it with a rationale,
  bound to this exact source and plan.

Deterministic string evidence only — no provider call, no fuzzy scoring.
Findings quote only the declared names (bounded), never other source text.
"""

import json
import re
import unicodedata
from dataclasses import dataclass

from app.creative.source_adapter.facts import FactDiscovery
from app.creative.source_adapter.plan import VirtualTree
from app.domain.business_truth import BusinessTruth

_CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_SKIPPED_DIRS = ("node_modules/", "dist/", "packages/")
_MAX_NAME = 80
# Words that say nothing about WHICH business a name is.
_GENERIC = frozenset(
    "the and for with our your web site home page official studio estudio clinic clinica "
    "del los las una por con para sus www com".split()
)
_SEPARATORS = re.compile(r"\s+[|·•—–:-]\s+")
_OG_SITE_NAME = re.compile(r"""["']og:site_name["']\s*,\s*content\s*:\s*["'`]([^"'`]{1,200})["'`]""")
_LD_TYPE = re.compile(
    r"""["']@type["']\s*:\s*["'](Organization|LocalBusiness|[A-Za-z]*Business|[A-Za-z]*Contractor|"""
    r"""MedicalClinic|Physiotherapy|Store|Restaurant)["']"""
)
_LD_NAME = re.compile(r"""["']?name["']?\s*:\s*["'`]([^"'`]{1,200})["'`]""")


@dataclass(frozen=True)
class Declaration:
    where: str
    value: str


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", folded) if len(w) >= 3 and w not in _GENERIC}


def _brand(value: str) -> str:
    """The brand part of a title such as "Lumen Physio — Physiotherapy in Lisbon"."""
    return _SEPARATORS.split(value.strip(), maxsplit=1)[0].strip()


def _clip(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= _MAX_NAME else value[: _MAX_NAME - 1] + "…"


def _skipped(path: str) -> bool:
    return path.startswith(_SKIPPED_DIRS) or any(f"/{d}" in path for d in _SKIPPED_DIRS)


def declarations(tree: VirtualTree, *, app_meta_file: str | None) -> list[Declaration]:
    """Every deterministic identity declaration in the (app-relative) tree."""
    found: list[Declaration] = []
    if app_meta_file and tree.exists(app_meta_file):
        try:
            meta = json.loads(tree.text(app_meta_file))
        except (ValueError, UnicodeDecodeError):
            meta = None
        if isinstance(meta, dict) and isinstance(meta.get("og_title"), str) and meta["og_title"].strip():
            found.append(Declaration(f"{app_meta_file} og_title", _brand(meta["og_title"])))
    for path in tree.paths():
        if _skipped(path):
            continue
        if path.endswith(".webmanifest"):
            try:
                data = json.loads(tree.text(path))
            except (ValueError, UnicodeDecodeError):
                continue
            for key in ("name", "short_name"):
                if isinstance(data, dict) and isinstance(data.get(key), str) and data[key].strip():
                    found.append(Declaration(f"{path} {key}", data[key].strip()))
                    break
        elif path.endswith(_CODE_SUFFIXES):
            try:
                text = tree.text(path)
            except UnicodeDecodeError:
                continue
            for m in _OG_SITE_NAME.finditer(text):
                found.append(Declaration(f"{path} og:site_name", m.group(1).strip()))
            for m in _LD_TYPE.finditer(text):
                name = _LD_NAME.search(text[max(0, m.start() - 300) : m.end() + 300])
                if name:
                    found.append(Declaration(f"{path} JSON-LD {m.group(1)} name", name.group(1).strip()))
    return [d for d in found if _words(d.value)]


def assess_identity(
    tree: VirtualTree, truth: BusinessTruth, facts: FactDiscovery, *, app_meta_file: str | None
) -> list[dict[str, str]]:
    declared = declarations(tree, app_meta_file=app_meta_file)
    if not declared:
        return []  # ABSENT: nothing to compare
    truth_name = truth.identity.name
    truth_words = _words(truth_name)
    bound = {b.field for b in facts.bindings}
    if "identity.name" in bound or any(_words(d.value) & truth_words for d in declared):
        return []  # COMPATIBLE
    services_presented = any(f.startswith("services.") for f in bound)
    city_presented = "location.city" in bound
    sources = {d.where.rsplit(" ", 1)[0] for d in declared}
    agreeing = len(sources) >= 2 and bool(set.intersection(*(_words(d.value) for d in declared)))
    evidence = "; ".join(f"{_clip(d.value)!r} ({d.where})" for d in declared[:4])
    subject = _clip(declared[0].value)
    if not services_presented and (not city_presented or agreeing):
        return [
            {
                "code": "source_identity_conflict",
                "severity": "review",
                "subject": subject,
                "detail": (
                    f"The export declares the business as {evidence}, but BusinessTruth is {_clip(truth_name)!r}. "
                    "BusinessTruth's name and services do not appear anywhere in the export"
                    + ("" if city_presented else ", nor does its city")
                    + ". Check that this is the right export for this business before building; approve only "
                    "if it is (for example a rebrand BusinessTruth has not caught up with)."
                ),
            }
        ]
    return [
        {
            "code": "source_identity_unconfirmed",
            "severity": "info",
            "subject": subject,
            "detail": (
                f"The export declares the business as {evidence}, not {_clip(truth_name)!r}, although some "
                "BusinessTruth facts do appear in it."
            ),
        }
    ]
