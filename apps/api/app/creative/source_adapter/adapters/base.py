"""The source-family adapter contract (H2), versioned.

GWA onboards an exported website through ONE adapter per source family
(e.g. `higgsfield-tanstack-static`). The adapter holds only knowledge of
that family — its framework, build system, file conventions and the
shapes its code takes — and expresses everything it changes as
AdaptationPlan operations. The platform integration (SDK, lead
transport, consent, legal, SEO, asset/CSP policy, artifact assembly,
contracts, QA evidence) is shared (platform_files.py, the pipeline).

    detect(manifest)                 does this adapter handle the export?
    assess(manifest, tree, overlay)  family supportability findings
    resolve(finding, manifest, tree) which findings the family handles, how
    csp_requirements(manifest, tree) CSP additions it needs (validated
                                     against the family policy, fail closed)
    locale(manifest, tree)           the site's language (platform texts)
    text_paths(manifest, tree)       where visitor-readable text lives
    build_spec(manifest, pages)      how it is built and what it must emit
    plan(context, builder)           the operations (dry-run on a copy)

An ExportOverlay is reviewed DATA for one specific export (pinned to its
snapshot SHA-256): human approvals of review findings, design decisions
that are not inferable (banner theme, where legal links sit, which frame
becomes the share image, which qualitative claims the owner confirms)
and approved design-preserving fixes, each tied to the findings it
resolves. It is not code and never branches platform behaviour on a
business.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.creative.source_adapter.classify import Finding
from app.creative.source_adapter.facts import FactDiscovery
from app.creative.source_adapter.forms import FormMapping
from app.creative.source_adapter.manifest import SourceManifest
from app.creative.source_adapter.plan import PlanBuilder, VirtualTree
from app.creative.source_adapter.records import AdapterError
from app.domain.business_truth import BusinessTruth
from app.publishing.security_headers import CspExtensions

ADAPTER_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class SiteContext:
    origin: str  # the site's canonical public origin (https://...)
    locale: str  # platform text locale (consent banner, legal pages)


@dataclass(frozen=True)
class BuildSpec:
    toolchain: str  # "bun"
    install: tuple[str, ...]  # trusted zone (host network, never runs scripts)
    sandbox_steps: tuple[tuple[str, tuple[str, ...]], ...]  # (label, argv) inside the R4 sandbox
    output_dir: str  # static output, relative to the app
    expected_pages: tuple[str, ...]  # html files the artifact must contain

    def to_dict(self) -> dict:
        return {
            "toolchain": self.toolchain,
            "install": list(self.install),
            "sandbox_steps": [{"label": label, "argv": list(argv)} for label, argv in self.sandbox_steps],
            "output_dir": self.output_dir,
            "expected_pages": list(self.expected_pages),
        }


@dataclass(frozen=True)
class OverlayPatch:
    """An approved, exact-once edit of the ORIGINAL export (applied first)."""

    path: str
    find: str
    replace: str
    reason: str
    category: str = "approved-fix"
    visible: str | None = None
    resolves: tuple[str, ...] = ()  # finding ids this patch resolves


@dataclass(frozen=True)
class LegalPresentation:
    """How legal pages/links are presented in THIS design (not inferable)."""

    nav_class: str | None = None
    link_class: str | None = None
    links_anchor: tuple[str, str] | None = None  # (module, fragment the links are inserted before)
    page_tsx: str | None = None  # a legal page component using the site's own classes


@dataclass(frozen=True)
class ExportOverlay:
    name: str
    snapshot_zip_sha256: str
    reviewed: str  # who/when/why (human review record)
    approvals: dict[str, str] = field(default_factory=dict)  # review finding id -> rationale
    resolutions: dict[str, str] = field(default_factory=dict)  # finding id -> how a patch resolves it
    patches: tuple[OverlayPatch, ...] = ()
    consent_theme: dict[str, str] | None = None  # --gwa-consent-* -> the site's own CSS values
    legal: LegalPresentation | None = None
    og_image_source: str | None = None  # app-relative raster the share image is cropped from
    owner_review_claims: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        resolved = {fid for patch in self.patches for fid in patch.resolves}
        unbacked = sorted(set(self.resolutions) - resolved)
        if unbacked:
            raise AdapterError(f"overlay {self.name}: resolutions without a patch performing them: {unbacked}")


@dataclass
class PlanContext:
    manifest: SourceManifest
    tree: VirtualTree  # the working-copy image the plan dry-runs on
    snapshot_app: Path  # the read-only snapshot app dir (analysis only)
    truth: BusinessTruth
    site: SiteContext
    overlay: ExportOverlay | None
    form_mappings: list[FormMapping]
    facts: FactDiscovery


class SourceFamilyAdapter(Protocol):
    adapter_id: str
    version: str
    contract_version: str
    family: str

    def detect(self, manifest: SourceManifest) -> bool: ...

    def assess(self, manifest: SourceManifest, tree: VirtualTree, overlay: ExportOverlay | None) -> list[Finding]: ...

    def resolve(self, finding: Finding, manifest: SourceManifest, tree: VirtualTree) -> str | None: ...

    def csp_requirements(self, manifest: SourceManifest, tree: VirtualTree) -> CspExtensions: ...

    def locale(self, manifest: SourceManifest, tree: VirtualTree) -> str: ...

    def text_paths(self, manifest: SourceManifest, tree: VirtualTree) -> list[str]: ...

    def build_spec(self, manifest: SourceManifest, pages: tuple[str, ...]) -> BuildSpec: ...

    def plan(self, context: PlanContext, builder: PlanBuilder) -> tuple[str, ...]:
        """Records the operations; returns the prerendered page paths."""
        ...
