"""Supportability classification (H2): can this export be adapted, and
what must a human decide first?

    SUPPORTED              every finding is info, or resolved by a named
                           adapter/overlay action;
    SUPPORTED_WITH_REVIEW  no open blocker, but review findings exist — the
                           adaptation proceeds only once each is resolved or
                           APPROVED by a human (recorded in the plan);
    UNSUPPORTED            at least one open blocker. Nothing is mutated.

A finding is `blocker | review | info`, with a stable id
`<code>:<subject>`. It can be RESOLVED only by an explicit action the
source-family adapter or the reviewed export overlay performs (the
resolution text says which), and a REVIEW finding can be APPROVED by a
human through the overlay. A blocker is never approvable: it is fixed in
the export, in BusinessTruth or in the platform — never by weakening a
check. Security is never "made to work": secrets, binaries, remote
scripts, non-registry dependencies and origins outside the family's CSP
policy stop the adapter.

Generic rules (every family) live here; family rules come from the
adapter (`assess`) and family knowledge of what it handles (`resolve`).
"""

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from app.creative.source_adapter.manifest import SourceManifest
from app.publishing.csp_policy import policy_for

if TYPE_CHECKING:
    from app.creative.source_adapter.adapters.base import ExportOverlay, SourceFamilyAdapter
    from app.creative.source_adapter.plan import VirtualTree

SUPPORTED = "SUPPORTED"
SUPPORTED_WITH_REVIEW = "SUPPORTED_WITH_REVIEW"
UNSUPPORTED = "UNSUPPORTED"

_KNOWN_SECRET_KINDS = frozenset(
    {
        "aws-access-key",
        "private-key",
        "anthropic-or-openai-key",
        "github-token",
        "slack-token",
        "stripe-secret",
        "google-api-key",
        "jwt",
    }
)
_NETWORK_CONTEXTS = frozenset({"stylesheet", "font", "script", "connect", "media", "preconnect", "reference"})

# The generic rule table (documentation + tests): code -> (severity, meaning).
GENERIC_RULES: dict[str, tuple[str, str]] = {
    "no_family_adapter": ("blocker", "no registered source-family adapter recognises this export"),
    "already_adapted": ("blocker", "the source already contains GWA platform integration; adapt the ORIGINAL export"),
    "design_critical_dependency": ("blocker", "the public site needs a package the export does not contain"),
    "non_registry_dependency": ("blocker", "a dependency is fetched from git/URL/file instead of the registry"),
    "secret_like_string": ("blocker", "a credential-shaped string is embedded in the source (review if generic)"),
    "environment_file": ("blocker", "an environment/credential file is part of the export"),
    "npmrc": ("blocker", ".npmrc can redirect the registry or carry tokens"),
    "trusted_dependencies": ("blocker", "trustedDependencies would run dependency install scripts"),
    "binary_executable": ("blocker", "an executable/binary file is part of the export (wasm: review)"),
    "remote_script": ("blocker", "live code loads a script from another origin"),
    "no_build_command": ("blocker", "package.json has no build script"),
    "network_origin_not_permitted": ("blocker", "live code fetches from an origin outside the family CSP policy"),
    "lifecycle_script": ("review", "an install lifecycle script (never run by the install)"),
    "dynamic_code": ("review", "eval / new Function in live code"),
    "raw_html_injection": ("review", "dangerouslySetInnerHTML in live code"),
    "process_env_access": ("review", "process.env read by client-reachable code"),
    "unscannable_module": ("review", "a live module the static inspection could not read"),
    "server_runtime": ("review", "live code needs a server runtime a static artifact does not have"),
    "host_hook": ("review", "live code talks to its builder host (globals / cross-window messages)"),
    "analytics_or_tracking": ("review", "tracking code that would bypass GWA consent"),
    "source_structured_data": ("review", "the export ships its own structured data (may state unverified facts)"),
    "no_lockfile": ("review", "no lockfile: dependency resolution is not reproducible"),
    "external_link": ("info", "a link to another site (navigation only, no fetch)"),
}


@dataclass
class Finding:
    code: str
    severity: str  # blocker | review | info
    subject: str
    detail: str
    source: str  # generic | family | forms | facts | claims
    resolution: str | None = None  # the adapter/overlay action that handles it
    approval: str | None = None  # the human approval (review findings only)

    @property
    def id(self) -> str:
        return f"{self.code}:{self.subject}"

    @property
    def open(self) -> bool:
        return self.resolution is None and self.approval is None and self.severity != "info"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "id": self.id, "open": self.open}


@dataclass
class Supportability:
    status: str
    adapter: str | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def ready_to_adapt(self) -> bool:
        return not any(f.open for f in self.findings)

    def open_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.open]

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return {
            "status": self.status,
            "adapter": self.adapter,
            "ready_to_adapt": self.ready_to_adapt,
            "counts": dict(sorted(counts.items())),
            "open": [f.id for f in self.open_findings()],
            "findings": [f.to_dict() for f in self.findings],
        }


def generic_findings(manifest: SourceManifest, family: str | None) -> list[Finding]:
    out: list[Finding] = []

    def add(code: str, subject: str, detail: str, severity: str | None = None) -> None:
        out.append(Finding(code, severity or GENERIC_RULES[code][0], subject, detail, "generic"))

    if manifest.already_adapted:
        add("already_adapted", "source", f"platform markers present: {manifest.already_adapted}")
    for module in manifest.modules["design_critical"]:
        add("design_critical_dependency", module, f"needs {manifest.modules['unavailable_packages']}")
    for dep in manifest.dependencies:
        if dep["kind"] not in ("registry", "workspace"):
            add("non_registry_dependency", dep["name"], f"{dep['section']}: {dep['spec']!r} ({dep['kind']})")
    if not manifest.build["command"]:
        add("no_build_command", "package.json", "no `build` script")
    if not manifest.package_manager["lockfile"]:
        add("no_lockfile", "package.json", "no lockfile")
    for item in manifest.security:
        code, path = item["code"], item["path"]
        if code == "secret_like_string":
            line = item["detail"].split(" at line ")[-1].split(" ")[0]
            add(
                code,
                f"{path}:{line}",
                item["detail"],
                "blocker" if item.get("kind") in _KNOWN_SECRET_KINDS else "review",
            )
        elif code == "binary_executable":
            add(code, path, item["detail"], "review" if "wasm" in item["detail"] else None)
        elif code == "lifecycle_script":
            add(code, str(item.get("script")), item["detail"])
        elif code in GENERIC_RULES and (item["live"] or code in ("environment_file", "npmrc", "trusted_dependencies")):
            add(code, path, item["detail"])
    for hook in manifest.host_hooks:
        add("host_hook", f"{hook['hook']}@{hook['file']}", f"{hook['hook']} in {hook['file']}")
    for vendor in sorted({a["vendor"] for a in manifest.analytics if a["live"]}):
        files = sorted({a["file"] for a in manifest.analytics if a["vendor"] == vendor and a["live"]})
        add("analytics_or_tracking", vendor, f"{vendor} in {files}")
    for item in manifest.structured_data:
        if item["live"]:
            add("source_structured_data", item["file"], "structured data authored by the builder")

    permitted: set[str] = set()
    if family is not None:
        policy = policy_for(family)
        permitted = set(policy.style_origins) | set(policy.font_origins)
    for origin in manifest.external_origins:
        if not origin["live"]:
            continue
        if origin["context"] == "link":
            add("external_link", origin["origin"], f"linked from {origin['files']}")
        elif origin["context"] in _NETWORK_CONTEXTS and origin["origin"] not in permitted:
            add(
                "network_origin_not_permitted",
                f"{origin['origin']} ({origin['context']})",
                f"{origin['context']} from {origin['origin']} in {origin['files']}",
            )
    return out


def classify(
    manifest: SourceManifest,
    adapter: "SourceFamilyAdapter | None",
    tree: "VirtualTree",
    extra: list[Finding] | None = None,
    overlay: "ExportOverlay | None" = None,
) -> Supportability:
    """Generic + family + extra (forms/facts/claims) findings, with every
    adapter resolution and overlay resolution/approval applied."""
    if adapter is None:
        finding = Finding("no_family_adapter", "blocker", "source", GENERIC_RULES["no_family_adapter"][1], "generic")
        return Supportability(UNSUPPORTED, None, [finding, *generic_findings(manifest, None)])
    findings = generic_findings(manifest, adapter.family) + adapter.assess(manifest, tree, overlay) + list(extra or [])
    for f in findings:
        if f.resolution is None:
            f.resolution = adapter.resolve(f, manifest, tree)
        if overlay is not None and f.resolution is None and f.id in overlay.resolutions:
            f.resolution = f"overlay {overlay.name}: {overlay.resolutions[f.id]}"
        if overlay is not None and f.resolution is None and f.severity == "review" and f.id in overlay.approvals:
            f.approval = f"overlay {overlay.name}: {overlay.approvals[f.id]}"
    findings.sort(key=lambda f: ({"blocker": 0, "review": 1, "info": 2}[f.severity], f.code, f.subject))
    if any(f.open and f.severity == "blocker" for f in findings):
        status = UNSUPPORTED
    elif any(f.severity == "review" for f in findings):
        status = SUPPORTED_WITH_REVIEW
    else:
        status = SUPPORTED
    return Supportability(status, f"{adapter.adapter_id}@{adapter.version}", findings)
