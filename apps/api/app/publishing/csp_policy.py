"""Source-family CSP policy (H1.1).

A website's `_headers` is always DERIVED by trusted platform code
(security_headers.generate_headers_file): the GWA baseline, plus the inline
script hashes of the built HTML, the public API origin and — here — the
additions its SOURCE FAMILY is allowed. A family is chosen by trusted code
when a job is created (generation_jobs.source_family) and travels with the
job; nothing a build, an export or a candidate contains can pick it or add
to it.

Two layers, both fail closed:

- a HARD ALLOWLIST of the only additions any family may ever carry
  (PERMITTED_*). A family policy outside it raises at import time;
- the per-family POLICY. An unknown family, or a source requesting more
  than its family's policy (validate_requested), raises
  UnsupportedCspRequirementError — nothing is silently dropped or widened.

CspExtensions itself already refuses anything but exact https origins, so
keywords ('unsafe-inline', 'unsafe-eval'), wildcards, scheme-only sources,
paths and `blob:`/`data:` can never be expressed as an origin. `script-src`
is never extended by any family.
"""

from enum import StrEnum

from app.publishing.security_headers import CspExtensions


class SourceFamily(StrEnum):
    # GWA's own engines (deterministic Astro sites, the generative Astro
    # engine): the unmodified GWA baseline.
    GWA_ASTRO = "gwa-astro"
    # A prerendered Higgsfield Supercomputer export (React + TanStack Start),
    # adapted by app.creative.source_adapter (H1). Its scroll-scrub engine
    # plays same-origin clips through blob: object URLs; its display face
    # (Cabinet Grotesk) is served by Fontshare's CSS API (api.fontshare.com
    # stylesheet -> cdn.fontshare.com font files).
    HIGGSFIELD_TANSTACK = "higgsfield-tanstack-static"


DEFAULT_SOURCE_FAMILY = SourceFamily.GWA_ASTRO

# The ONLY additions any family may ever carry.
PERMITTED_STYLE_ORIGINS = frozenset({"https://api.fontshare.com"})
PERMITTED_FONT_ORIGINS = frozenset({"https://cdn.fontshare.com"})
PERMITTED_MEDIA_BLOB = frozenset({SourceFamily.HIGGSFIELD_TANSTACK})

_POLICIES: dict[SourceFamily, CspExtensions] = {
    SourceFamily.GWA_ASTRO: CspExtensions(),
    SourceFamily.HIGGSFIELD_TANSTACK: CspExtensions(
        media_blob=True,
        style_origins=("https://api.fontshare.com",),
        font_origins=("https://cdn.fontshare.com",),
    ),
}


class UnsupportedCspRequirementError(ValueError):
    """A family or source asked for something the platform does not allow."""


def assert_permitted(family: SourceFamily, policy: CspExtensions) -> None:
    if policy.media_blob and family not in PERMITTED_MEDIA_BLOB:
        raise UnsupportedCspRequirementError(f"{family}: media-src blob: is not permitted")
    extra = (set(policy.style_origins) - PERMITTED_STYLE_ORIGINS) | (set(policy.font_origins) - PERMITTED_FONT_ORIGINS)
    if extra:
        raise UnsupportedCspRequirementError(f"{family}: origins outside the platform allowlist: {sorted(extra)}")


for _family, _policy in _POLICIES.items():
    assert_permitted(_family, _policy)


def parse_family(value: str) -> SourceFamily:
    try:
        return SourceFamily(value)
    except ValueError:
        raise UnsupportedCspRequirementError(f"unknown source family: {value!r}") from None


def policy_for(family: str) -> CspExtensions:
    """The trusted CSP additions for `family`; raises for an unknown family."""
    return _POLICIES[parse_family(family)]


def validate_requested(family: str, requested: CspExtensions) -> CspExtensions:
    """A source (an adapter mapping) states what it needs; accepted only if
    every requirement is inside its family's policy. Returns the FAMILY
    policy — the single policy every stage then derives headers from."""
    policy = policy_for(family)
    problems: list[str] = []
    if requested.media_blob and not policy.media_blob:
        problems.append("media-src blob:")
    problems += sorted(set(requested.style_origins) - set(policy.style_origins))
    problems += sorted(set(requested.font_origins) - set(policy.font_origins))
    if problems:
        raise UnsupportedCspRequirementError(f"{family}: requirements outside its policy: {problems}")
    return policy
