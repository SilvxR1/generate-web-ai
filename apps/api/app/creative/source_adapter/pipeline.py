"""adapt_export (H1): the end-to-end adapter pipeline for ONE exported source.

    export ZIP
      -> snapshot_export     immutable, hash-identified ORIGINAL (read-only)
      -> copy                the ADAPTED working copy (all edits happen here)
      -> portability_cleanup unavailable private workspace packages removed
      -> apply_mapping       BusinessTruth bindings + GWA platform integration
      -> prepare_dependencies trusted, validated `bun install --ignore-scripts`
      -> build_in_sandbox    the export's own build in the R4 sandbox, no network
      -> assemble_static_artifact  platform runtime, robots/sitemap, _headers
      -> PlatformContract + TruthContract (unmodified)
      -> artifact_sha256 / pack_artifact (the Build Once conventions)

READY only when both contracts have no blocking finding. Nothing here
uploads, publishes or talks to any provider.
"""

import json
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from app.creative.frontend_engine.sandbox import SandboxRunner, detect_runner
from app.creative.source_adapter.cleanup import portability_cleanup
from app.creative.source_adapter.mapping import SiteContext, SourceMapping, apply_mapping, resolved_csp
from app.creative.source_adapter.records import AdapterError, sha256_hex
from app.creative.source_adapter.snapshot import snapshot_export
from app.creative.source_adapter.static_artifact import assemble_static_artifact
from app.creative.source_adapter.static_build import Toolchain, build_in_sandbox, prepare_dependencies
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import derive_business_truth
from app.publishing.artifact_store import artifact_sha256, pack_artifact, unpack_artifact
from app.qa.platform_contract import validate_platform_contract
from app.qa.truth_contract import validate_truth_contract

_EXTERNAL_ANCHOR = re.compile(r"<a\b([^>]*\bhref\s*=\s*\"(?:https?:)?//[^\"]*\"[^>]*)>", re.IGNORECASE)


def external_links(files: dict[str, bytes]) -> list[dict[str, object]]:
    """Every external <a> in the artifact and whether a new-tab link is safe."""
    links: list[dict[str, object]] = []
    for path, data in sorted(files.items()):
        if not path.endswith(".html"):
            continue
        for match in _EXTERNAL_ANCHOR.finditer(data.decode("utf-8", errors="ignore")):
            attrs = match.group(1)
            new_tab = 'target="_blank"' in attrs
            links.append({"page": path, "new_tab": new_tab, "safe": not new_tab or "noopener" in attrs})
    return links


_FONTSOURCE_FAMILIES = ("inter-tight", "ibm-plex-mono")
_PLATFORM_FILES = frozenset({"_headers", "robots.txt", "sitemap.xml"})


def asset_provenance(files: dict[str, bytes], *, snapshot_files: dict[str, str], app_dir: str) -> dict:
    """H1.2: where every artifact file comes from. An export asset must be
    byte-identical to the immutable snapshot's public/ file (same SHA-256),
    so the artifact provably persists the ORIGINAL media, not a copy that
    drifted; everything else is labelled by origin."""
    counts: dict[str, int] = {}
    media: list[dict[str, str]] = []
    for path, data in sorted(files.items()):
        digest = sha256_hex(data)
        if snapshot_files.get(f"{app_dir}/public/{path}") == digest:
            origin = "higgsfield-export"
        elif path in _PLATFORM_FILES:
            origin = "gwa-platform"
        elif path == "og-image.jpg":
            origin = "gwa-derived"
        elif path.endswith((".woff", ".woff2")) and any(f in path for f in _FONTSOURCE_FAMILIES):
            origin = "self-hosted-ofl-font"
        else:
            origin = "build-output"
        counts[origin] = counts.get(origin, 0) + 1
        if origin != "build-output":
            media.append({"path": path, "origin": origin, "sha256": digest})
    return {"counts": counts, "files": media}


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


def adapt_export(
    zip_path: Path,
    work_root: Path,
    mapping: SourceMapping,
    business_config: BusinessConfig,
    *,
    business_id: str,
    api_base_url: str,
    site_origin: str,
    runner: SandboxRunner | None = None,
    toolchain: Toolchain | None = None,
) -> dict:
    """Runs the pipeline into `work_root` (must not exist) and returns the
    report (also written to work_root/h1-report.json)."""
    csp_extensions = resolved_csp(mapping)  # H1.1: fail closed before any work
    if work_root.exists():
        raise AdapterError(f"work root already exists: {work_root}")
    work_root.mkdir(parents=True)

    snapshot = snapshot_export(zip_path, work_root / "original")
    (work_root / "source-manifest.json").write_text(json.dumps(snapshot.manifest(), indent=2), encoding="utf-8")
    if snapshot.zip_sha256 != mapping.export_zip_sha256:
        raise AdapterError(f"mapping {mapping.name} was written for another export (sha256 {snapshot.zip_sha256})")

    adapted_root = work_root / "adapted"
    shutil.copytree(snapshot.root, adapted_root)
    _make_writable(adapted_root)
    app = adapted_root / snapshot.app_dir

    truth = derive_business_truth(business_config=business_config)
    cleanup = portability_cleanup(app)
    site = SiteContext(origin=site_origin.rstrip("/"), locale=mapping.locale)
    changes = cleanup.changes + apply_mapping(app, mapping, truth, site)
    (work_root / "changes.json").write_text(json.dumps([asdict(c) for c in changes], indent=2), encoding="utf-8")

    toolchain = toolchain or Toolchain.detect()
    started = time.monotonic()
    prepare_dependencies(app, toolchain, frozen=False)
    install_seconds = round(time.monotonic() - started, 1)

    runner = runner or detect_runner()
    started = time.monotonic()
    client = build_in_sandbox(app, toolchain, runner)
    build_seconds = round(time.monotonic() - started, 1)

    artifact = assemble_static_artifact(
        client,
        business_id=business_id,
        api_base_url=api_base_url,
        site_origin=site_origin,
        csp_extensions=csp_extensions,
        locale=mapping.locale,
    )
    platform = validate_platform_contract(artifact.files, business_config=business_config)
    truth_result = validate_truth_contract(artifact.files, business_truth=truth)

    sha256 = artifact_sha256(artifact)
    archive = pack_artifact(artifact)
    if artifact_sha256(unpack_artifact(archive)) != sha256 or pack_artifact(unpack_artifact(archive)) != archive:
        raise AdapterError("the packed artifact does not round-trip to the same identity")
    ready = platform.passed and truth_result.passed
    readiness = [asdict(f) for f in (mapping.readiness(truth) if mapping.readiness is not None else [])]
    provenance = asset_provenance(
        artifact.files, snapshot_files={f.path: f.sha256 for f in snapshot.files}, app_dir=snapshot.app_dir
    )
    (work_root / "artifact.tar.gz").write_bytes(archive)

    report = {
        "mapping": mapping.name,
        "source": {
            "zip_sha256": snapshot.zip_sha256,
            "files": len(snapshot.files),
            "bytes": sum(f.size for f in snapshot.files),
            "assets": len(snapshot.assets),
            "package_manager": snapshot.package_manager,
            "lockfile": snapshot.lockfile,
            "lockfile_sha256": snapshot.lockfile_sha256,
            "build_command": snapshot.build_command,
            "framework": snapshot.framework,
        },
        "cleanup": {"unavailable_packages": cleanup.unavailable_packages, "removed_routes": cleanup.removed_routes},
        "changes": {
            "total": len(changes),
            "by_kind": {kind: sum(c.kind == kind for c in changes) for kind in sorted({c.kind for c in changes})},
            "visible": [{"path": c.path, "visible": c.visible} for c in changes if c.visible],
        },
        "unbound_content": list(mapping.unbound_content),
        "source_family": mapping.source_family,
        "headers_sha256": sha256_hex(artifact.files["_headers"]),
        "adapted_lockfile_sha256": sha256_hex((app / "bun.lock").read_bytes()),
        "install_seconds": install_seconds,
        "build": {"seconds": build_seconds, "runner": runner.name, "limits_enforced": runner.limits_enforced()},
        "artifact": {
            "sha256": sha256,
            "archive_sha256": sha256_hex(archive),
            "archive_bytes": len(archive),
            "files": len(artifact.files),
            "bytes": sum(len(v) for v in artifact.files.values()),
            "html_pages": sorted(p for p in artifact.files if p.endswith(".html")),
            "external_links": external_links(artifact.files),
        },
        "platform_contract": {
            "version": platform.version,
            "passed": platform.passed,
            "findings": [f.model_dump(mode="json") for f in platform.findings],
        },
        "truth_contract": {
            "version": truth_result.version,
            "passed": truth_result.passed,
            "findings": [f.model_dump(mode="json") for f in truth_result.findings],
        },
        "ready": ready,
        # H1.2: owner/legal input still needed for a real launch (separate from
        # artifact validity, which is the contracts' verdict above).
        "readiness_findings": readiness,
        "launch_ready": ready and not any(f["severity"] == "launch_blocker" for f in readiness),
        "asset_provenance": provenance,
    }
    (work_root / "h1-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
